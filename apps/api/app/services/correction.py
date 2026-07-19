"""CorrectionService — aplica changes ao target resolvido pelo TargetMatcher.

SP-70/SP-71/SP-72/SP-73/SP-74:
- Recompute automático dos macros/kcal_burned quando quantidade mudar.
- audit_event before/after obrigatório (INV-10 / Const. Art. III §11).
- Dia com status='closed' bloqueia mutação → DayClosedError (INV-5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.integrations.nutrition.catalog import LookupQuery
from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.models import (
    ActivityRecord,
    BeverageRecord,
    DayLog,
    FoodItem,
    User,
    WaterRecord,
)
from app.repositories.food import AuditEventRepository
from app.schemas.llm import LLMEnvelope
from app.services.activity_calculator import ActivityCalculator
from app.services.correction_matcher import (
    AmbiguousTarget,  # noqa: F401 — re-exportado
    MatchError,  # noqa: F401 — re-exportado
    NoTargetFound,  # noqa: F401 — re-exportado
    TargetKind,
    TargetMatcher,
)
from app.services.nutrition_calculator import NutritionCalculator


class DayClosedError(Exception):
    """SP-73/SP-82 (INV-5): dia com status='closed' é imutável."""


@dataclass(slots=True)
class CorrectionResult:
    kind: TargetKind
    entity_id: uuid.UUID
    changed_fields: dict[str, tuple[Any, Any]]
    warnings: list[dict[str, Any]]


class CorrectionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.matcher = TargetMatcher(session)
        self.audit = AuditEventRepository(session)

    async def apply_from_llm(
        self,
        *,
        user: User,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        envelope: LLMEnvelope,
    ) -> CorrectionResult:
        if envelope.correction is None:
            raise ValidationAppError(
                "envelope missing correction block",
                code="invalid_correction_envelope",
            )
        await _ensure_day_open(self.session, day_log_id)

        candidate = await self.matcher.resolve(
            day_log_id=day_log_id,
            target_hint=envelope.correction.target_hint,
        )
        changes = envelope.correction.changes

        before = _snapshot(candidate.entity, candidate.kind)
        warnings: list[dict[str, Any]] = []
        changed: dict[str, tuple[Any, Any]] = {}

        if candidate.kind == TargetKind.FOOD:
            changed = await self._apply_food_changes(candidate.entity, changes, warnings, user)
        elif candidate.kind == TargetKind.WATER:
            changed = _apply_water_changes(candidate.entity, changes)
        elif candidate.kind == TargetKind.BEVERAGE:
            changed = await self._apply_beverage_changes(candidate.entity, changes, warnings)
        elif candidate.kind == TargetKind.ACTIVITY:
            changed = _apply_activity_changes(candidate.entity, changes, user, warnings)

        if not changed:
            raise ValidationAppError(
                "no applicable changes for target",
                code="correction_no_effect",
            )

        # source becomes user_corrected quando aplicável (food/beverage).
        if candidate.kind in (TargetKind.FOOD, TargetKind.BEVERAGE):
            candidate.entity.source = "user_corrected"

        await self.session.flush()

        after = _snapshot(candidate.entity, candidate.kind)
        await self.audit.record(
            user_id=user.id,
            entity_type=_entity_type_for_audit(candidate.kind),
            entity_id=candidate.entity_id,
            action="correct",
            actor="llm",
            message_id=message_id,
            before=before,
            after=after,
        )
        return CorrectionResult(
            kind=candidate.kind,
            entity_id=candidate.entity_id,
            changed_fields=changed,
            warnings=warnings,
        )

    async def _apply_food_changes(
        self,
        item: FoodItem,
        changes: dict[str, Any],
        warnings: list[dict[str, Any]],
        user: User,
    ) -> dict[str, tuple[Any, Any]]:
        changed: dict[str, tuple[Any, Any]] = {}
        new_grams = _extract_grams(changes)
        new_ml = _extract_ml(changes)

        if new_grams is not None:
            changed["grams"] = (
                _to_float(item.grams),
                float(new_grams),
            )
            item.grams = new_grams
        if new_ml is not None:
            changed["ml"] = (_to_float(item.ml), float(new_ml))
            item.ml = new_ml

        # Se veio quantity/unit direto, também aplicamos.
        if "quantity" in changes and changes["quantity"] is not None:
            new_q = Decimal(str(changes["quantity"]))
            changed["quantity"] = (_to_float(item.quantity), float(new_q))
            item.quantity = new_q
        if "unit" in changes and changes["unit"] is not None:
            unit = str(changes["unit"])
            changed["unit"] = (item.unit, unit)
            item.unit = unit

        # Recompute macros se quantidade mudou e temos catalog.
        if changed and (new_grams is not None or new_ml is not None):
            hit = None
            if item.catalog_ref_id is not None:
                catalog = LocalTBCACatalog(self.session)
                hit = await catalog.lookup(LookupQuery(name=item.normalized_name, brand=item.brand))
            computed = NutritionCalculator.compute(hit=hit, grams=item.grams, ml=item.ml)
            for field in (
                "kcal",
                "protein_g",
                "carbs_g",
                "fat_g",
                "fiber_g",
                "sodium_mg",
                "calcium_mg",
                "iron_mg",
                "potassium_mg",
            ):
                new_val = getattr(computed, field)
                old_val = getattr(item, field)
                if old_val != new_val:
                    changed[field] = (_to_float(old_val), _to_float(new_val))
                    setattr(item, field, new_val)
            for reason in computed.reasons:
                warnings.append({"code": reason, "item_id": str(item.id)})

        # SP-24 revalida: se depois da correção `confidence`>=0.5 e catálogo
        # hit, needs_confirmation desce.
        if item.needs_confirmation and item.catalog_ref_id is not None:
            item.needs_confirmation = False
            changed["needs_confirmation"] = (True, False)

        return changed

    async def _apply_beverage_changes(
        self,
        record: BeverageRecord,
        changes: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> dict[str, tuple[Any, Any]]:
        changed: dict[str, tuple[Any, Any]] = {}
        new_ml = _extract_ml(changes) or _extract_volume_ml(changes)
        if new_ml is not None:
            int_ml = int(new_ml)
            changed["volume_ml"] = (record.volume_ml, int_ml)
            record.volume_ml = int_ml

        if changed:
            catalog = LocalTBCACatalog(self.session)
            hit = None
            if record.catalog_ref_id is not None:
                hit = await catalog.lookup(
                    LookupQuery(name=record.normalized_name, brand=record.brand)
                )
            computed = NutritionCalculator.compute(
                hit=hit, grams=None, ml=Decimal(str(record.volume_ml))
            )
            for field in (
                "kcal",
                "protein_g",
                "carbs_g",
                "fat_g",
                "fiber_g",
                "sodium_mg",
                "calcium_mg",
                "iron_mg",
                "potassium_mg",
            ):
                new_val = getattr(computed, field)
                old_val = getattr(record, field)
                if old_val != new_val:
                    changed[field] = (_to_float(old_val), _to_float(new_val))
                    setattr(record, field, new_val)
            for reason in computed.reasons:
                warnings.append({"code": reason, "record_id": str(record.id)})
        return changed


async def _ensure_day_open(session: AsyncSession, day_log_id: uuid.UUID) -> None:
    day_log = await session.get(DayLog, day_log_id)
    if day_log is None:
        raise ValidationAppError(f"day_log {day_log_id} not found", code="day_log_not_found")
    if day_log.status == "closed":
        raise DayClosedError()


def _apply_water_changes(
    record: WaterRecord, changes: dict[str, Any]
) -> dict[str, tuple[Any, Any]]:
    changed: dict[str, tuple[Any, Any]] = {}
    new_ml = _extract_volume_ml(changes) or _extract_ml(changes)
    if new_ml is not None:
        int_ml = int(new_ml)
        changed["volume_ml"] = (record.volume_ml, int_ml)
        record.volume_ml = int_ml
    return changed


def _apply_activity_changes(
    record: ActivityRecord,
    changes: dict[str, Any],
    user: User,
    warnings: list[dict[str, Any]],
) -> dict[str, tuple[Any, Any]]:
    changed: dict[str, tuple[Any, Any]] = {}
    new_duration = _extract_first(changes, "duration_minutes", "minutes")
    new_intensity = changes.get("intensity")
    reported_kcal = _extract_first(changes, "kcal_burned", "kcal_burned_reported")

    if new_duration is not None:
        dur = Decimal(str(new_duration))
        if dur > 0:
            changed["duration_minutes"] = (
                _to_float(record.duration_minutes),
                float(dur),
            )
            record.duration_minutes = dur
    if new_intensity is not None and new_intensity in {
        "light",
        "moderate",
        "vigorous",
        "unknown",
    }:
        changed["intensity"] = (record.intensity, new_intensity)
        record.intensity = new_intensity

    if reported_kcal is not None:
        kcal = Decimal(str(reported_kcal))
        changed["kcal_burned"] = (_to_float(record.kcal_burned), float(kcal))
        record.kcal_burned = kcal
        if record.calc_method != "user_manual":
            changed["calc_method"] = (record.calc_method, "user_manual")
            record.calc_method = "user_manual"
    elif changed:
        # Recompute via calculator se peso está disponível.
        if user.weight_kg is None:
            warnings.append(
                {
                    "code": "missing_weight_kg",
                    "record_id": str(record.id),
                }
            )
        else:
            computation = ActivityCalculator.compute(
                activity_type=record.activity_type,
                intensity=record.intensity,
                duration_minutes=record.duration_minutes,
                weight_kg=Decimal(str(user.weight_kg)),
            )
            if computation.kcal_burned != record.kcal_burned:
                changed["kcal_burned"] = (
                    _to_float(record.kcal_burned),
                    float(computation.kcal_burned),
                )
                record.kcal_burned = computation.kcal_burned
            if computation.met_value != record.met_value:
                changed["met_value"] = (
                    _to_float(record.met_value),
                    _to_float(computation.met_value),
                )
                record.met_value = computation.met_value
            for reason in computation.reasons:
                warnings.append({"code": reason, "record_id": str(record.id)})
    return changed


def _extract_grams(changes: dict[str, Any]) -> Decimal | None:
    for key in ("grams", "grams_estimate"):
        v = changes.get(key)
        if v is not None:
            return Decimal(str(v))
    # SP-70: "corrija para 220g" — quantity=220 unit=g é grams
    unit = changes.get("unit")
    quantity = changes.get("quantity")
    if quantity is not None and unit in ("g", "gr", "gram", "gramas", "grama"):
        return Decimal(str(quantity))
    return None


def _extract_ml(changes: dict[str, Any]) -> Decimal | None:
    v = changes.get("ml") or changes.get("ml_estimate")
    if v is not None:
        return Decimal(str(v))
    quantity = changes.get("quantity")
    unit = changes.get("unit")
    if quantity is not None and unit in ("ml", "mililitros", "mililitro"):
        return Decimal(str(quantity))
    return None


def _extract_volume_ml(changes: dict[str, Any]) -> Decimal | None:
    v = changes.get("volume_ml")
    if v is not None:
        return Decimal(str(v))
    return None


def _extract_first(changes: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if changes.get(key) is not None:
            return changes[key]
    return None


def _to_float(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _entity_type_for_audit(kind: TargetKind) -> str:
    return {
        TargetKind.FOOD: "food_item",
        TargetKind.WATER: "water_record",
        TargetKind.BEVERAGE: "beverage_record",
        TargetKind.ACTIVITY: "activity_record",
    }[kind]


def _snapshot(entity: Any, kind: TargetKind) -> dict[str, Any]:
    """Serializa o registro para audit before/after."""
    if kind == TargetKind.FOOD:
        return {
            "detected_name": entity.detected_name,
            "grams": _to_float(entity.grams),
            "ml": _to_float(entity.ml),
            "quantity": _to_float(entity.quantity),
            "unit": entity.unit,
            "kcal": _to_float(entity.kcal),
            "protein_g": _to_float(entity.protein_g),
            "carbs_g": _to_float(entity.carbs_g),
            "fat_g": _to_float(entity.fat_g),
            "needs_confirmation": entity.needs_confirmation,
            "source": entity.source,
        }
    if kind == TargetKind.WATER:
        return {"volume_ml": entity.volume_ml}
    if kind == TargetKind.BEVERAGE:
        return {
            "detected_name": entity.detected_name,
            "volume_ml": entity.volume_ml,
            "kcal": _to_float(entity.kcal),
            "source": entity.source,
        }
    return {
        "detected_name": entity.detected_name,
        "activity_type": entity.activity_type,
        "duration_minutes": _to_float(entity.duration_minutes),
        "intensity": entity.intensity,
        "kcal_burned": _to_float(entity.kcal_burned),
        "calc_method": entity.calc_method,
        "met_value": _to_float(entity.met_value),
    }
