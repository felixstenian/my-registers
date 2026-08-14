"""Testes do `CatalogBackfillService` — reseed do catálogo + backfill de itens zerados.

Cobre o script de correção one-off usado após a investigação de itens
legados com `kcal=0` (dev/prod seedado de versão antiga do CSV):

- `reseed_catalog`: re-roda `seed_from_csv` (upsert idempotente) para
  inserir fatos TBCA faltantes; não toca em `manual`/`label_ocr`.
- `backfill_zeroed_items`: liga item zerado ao catálogo, recomputa macros,
  grava audit e recomputa snapshot; pula dias fechados (INV-5) a menos que
  `include_closed`.

Const. Art. II §5/§10 (determinismo/recompute), Art. III §11 (auditoria),
Art. VIII §28 (dias fechados).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.seed import seed_from_csv
from app.models import AuditEvent, DailySnapshot, FoodItem, FoodRecord, NutrientFact
from app.repositories.day_log import DayLogRepository
from app.services.catalog_backfill import CatalogBackfillService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _day_log(session: AsyncSession, user, *, days_ago: int = 0):
    return await DayLogRepository(session).get_or_create(
        user_id=user.id, log_date=(datetime.now(UTC).date() - timedelta(days=days_ago))
    )


async def _create_zeroed_item(
    session: AsyncSession, user, dl_id, *, detected: str, normalized: str, grams=None
) -> FoodItem:
    """Cria food_item zerado (kcal=0, catalog_ref_id NULL) diretamente no DB."""
    record = FoodRecord(
        user_id=user.id,
        day_log_id=dl_id,
        meal_slot="lunch",
        occurred_at=datetime.now(UTC),
    )
    session.add(record)
    await session.flush()
    item = FoodItem(
        food_record_id=record.id,
        detected_name=detected,
        normalized_name=normalized,
        brand=None,
        quantity=None,
        unit="g" if grams else None,
        grams=Decimal(str(grams)) if grams else None,
        ml=None,
        source="llm",
        confidence=Decimal("0.9"),
        is_estimate=False,
        needs_confirmation=False,
        catalog_ref_id=None,
        kcal=Decimal("0"),
        protein_g=Decimal("0"),
        carbs_g=Decimal("0"),
        fat_g=Decimal("0"),
        fiber_g=Decimal("0"),
        sodium_mg=Decimal("0"),
        calcium_mg=Decimal("0"),
        iron_mg=Decimal("0"),
        potassium_mg=Decimal("0"),
    )
    session.add(item)
    await session.flush()
    return item


# ---------------------------------------------------------------------------
# reseed_catalog
# ---------------------------------------------------------------------------


async def test_reseed_inserts_missing_facts_and_is_idempotent(db_session: AsyncSession):
    """Fatos faltantes inseridos; fatos existentes atualizados; idempotente."""
    # Simula o banco antigo: um fato TBCA existente (será atualizado pelo
    # seed) e ausência total de `pepino_cru` (será inserido).
    old_fact = NutrientFact(
        canonical_name="brocoll_cozido",
        aliases=["brocoll_cozido"],
        source="TBCA_2023",
        basis="per_100g",
        kcal=Decimal("25"),
        protein_g=Decimal("0"),
        carbs_g=Decimal("0"),
        fat_g=Decimal("0"),
        fiber_g=Decimal("0"),
        sodium_mg=None,
        calcium_mg=None,
        iron_mg=None,
        potassium_mg=None,
    )
    db_session.add(old_fact)
    await db_session.flush()
    await db_session.commit()

    service = CatalogBackfillService(db_session)
    result = await service.reseed_catalog()
    await db_session.commit()

    assert result.seed_inserted > 0

    # Fato que não existia foi inserido com valores do CSV atual.
    pepino = (
        await db_session.execute(
            select(NutrientFact).where(
                NutrientFact.canonical_name == "pepino_cru",
                NutrientFact.source == "TBCA_2023",
            )
        )
    ).scalar_one_or_none()
    assert pepino is not None
    assert pepino.kcal == Decimal("12")

    # Nomes no banco são a forma normalizada do CSV — NENHUM rename.
    # `brocolis_cozido` no CSV vira `brocoll_cozido` (singularize) no banco.
    brocoll = (
        await db_session.execute(
            select(NutrientFact).where(NutrientFact.canonical_name == "brocoll_cozido")
        )
    ).scalar_one_or_none()
    assert brocoll is not None
    assert brocoll.kcal == Decimal("25")
    # O nome bruto do CSV NUNCA é inserido como canonical.
    raw = (
        await db_session.execute(
            select(NutrientFact.id).where(NutrientFact.canonical_name == "brocolis_cozido")
        )
    ).scalar_one_or_none()
    assert raw is None

    # Idempotência: rodar de novo não re-insere.
    second = await service.reseed_catalog()
    await db_session.commit()
    assert second.seed_inserted == 0


async def test_reseed_does_not_touch_manual_facts(db_session: AsyncSession):
    """Fatos `manual`/`label_ocr` nunca são sobrescritos pelo reseed."""
    manual = NutrientFact(
        canonical_name="pao_franc",
        aliases=["pao_franc"],
        source="manual",
        basis="per_100g",
        kcal=Decimal("999"),
        protein_g=Decimal("0"),
        carbs_g=Decimal("0"),
        fat_g=Decimal("0"),
        fiber_g=Decimal("0"),
        sodium_mg=None,
        calcium_mg=None,
        iron_mg=None,
        potassium_mg=None,
    )
    db_session.add(manual)
    await db_session.flush()
    await db_session.commit()

    service = CatalogBackfillService(db_session)
    await service.reseed_catalog()
    await db_session.commit()

    refreshed = await db_session.get(NutrientFact, manual.id)
    assert refreshed is not None
    assert refreshed.source == "manual"
    assert refreshed.kcal == Decimal("999")
    assert refreshed.canonical_name == "pao_franc"


# ---------------------------------------------------------------------------
# backfill_zeroed_items
# ---------------------------------------------------------------------------


async def test_backfill_links_zeroed_item_to_catalog(db_session: AsyncSession, admin_user):
    """Item zerado com nome no catálogo é ligado, macros recomputados,
    audit gravado e snapshot do dia atualizado."""
    await seed_from_csv(db_session)
    await db_session.commit()

    dl = await _day_log(db_session, admin_user)
    item = await _create_zeroed_item(
        db_session,
        admin_user,
        dl.id,
        detected="pepino",
        normalized="pepino",
        grams=60,
    )
    await db_session.commit()

    service = CatalogBackfillService(db_session)
    result = await service.backfill_zeroed_items()
    await db_session.commit()

    assert result.fixed == 1
    assert result.unresolved == []
    assert result.skipped_closed == []
    assert result.recomputed_days == 1

    await db_session.refresh(item)
    assert item.catalog_ref_id is not None
    # 60g × 12 kcal/100g = 7.2 kcal
    assert item.kcal == Decimal("7.20")
    assert item.source == "user_corrected"
    assert item.needs_confirmation is False

    snap = (
        await db_session.execute(select(DailySnapshot).where(DailySnapshot.day_log_id == dl.id))
    ).scalar_one()
    assert snap.kcal_in == Decimal("7.20")

    audit = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_id == item.id, AuditEvent.action == "correct"
            )
        )
    ).scalar_one()
    assert audit.after["backfill"] is True
    assert audit.before["catalog_ref_id"] is None


async def test_backfill_fills_serving_grams_when_missing(db_session: AsyncSession, admin_user):
    """Item sem grams/ml e com hit → usa `serving_grams` e marca is_estimate."""
    await seed_from_csv(db_session)
    await db_session.commit()

    dl = await _day_log(db_session, admin_user)
    item = await _create_zeroed_item(
        db_session, admin_user, dl.id, detected="cuscuz", normalized="cuscuz"
    )
    await db_session.commit()

    service = CatalogBackfillService(db_session)
    result = await service.backfill_zeroed_items()
    await db_session.commit()

    assert result.fixed == 1
    await db_session.refresh(item)
    assert item.catalog_ref_id is not None
    assert item.grams == Decimal("100")
    assert item.kcal > 0
    assert item.is_estimate is True


async def test_backfill_reports_unresolved(db_session: AsyncSession, admin_user):
    """Item sem hit no catálogo vai para `unresolved` (não é tocado)."""
    await seed_from_csv(db_session)
    await db_session.commit()

    dl = await _day_log(db_session, admin_user)
    item = await _create_zeroed_item(
        db_session,
        admin_user,
        dl.id,
        detected="sonho de Nutella",
        normalized="sonho_com_nutella",
        grams=80,
    )
    await db_session.commit()

    service = CatalogBackfillService(db_session)
    result = await service.backfill_zeroed_items()
    await db_session.commit()

    assert result.fixed == 0
    assert result.unresolved == ["sonho de Nutella"]
    await db_session.refresh(item)
    assert item.catalog_ref_id is None
    assert item.kcal == Decimal("0")


async def test_backfill_skips_closed_days_by_default(db_session: AsyncSession, admin_user):
    """INV-5: dias fechados pulados por padrão; incluídos com flag."""
    await seed_from_csv(db_session)
    await db_session.commit()

    dl = await _day_log(db_session, admin_user, days_ago=1)
    await _create_zeroed_item(
        db_session, admin_user, dl.id, detected="pepino", normalized="pepino", grams=60
    )
    await db_session.commit()

    # Fecha o dia (INV-5).
    dl.status = "closed"
    await db_session.commit()

    service = CatalogBackfillService(db_session)
    result = await service.backfill_zeroed_items()
    await db_session.commit()
    assert result.skipped_closed == ["pepino"]
    assert result.fixed == 0

    result_open = await service.backfill_zeroed_items(include_closed=True)
    await db_session.commit()
    assert result_open.fixed == 1
    assert result_open.skipped_closed == []


async def test_backfill_skips_deleted_items(db_session: AsyncSession, admin_user):
    """Itens soft-deleted (`deleted_at IS NOT NULL`) não são varridos."""
    await seed_from_csv(db_session)
    await db_session.commit()

    dl = await _day_log(db_session, admin_user)
    item = await _create_zeroed_item(
        db_session, admin_user, dl.id, detected="pepino", normalized="pepino", grams=60
    )
    item.deleted_at = datetime.now(UTC)
    await db_session.commit()

    service = CatalogBackfillService(db_session)
    result = await service.backfill_zeroed_items()
    await db_session.commit()
    assert result.fixed == 0
    assert result.scanned == 0
