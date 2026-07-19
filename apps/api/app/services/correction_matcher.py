"""TargetMatcher — resolve `target_hint` do LLM contra os registros vivos
do dia (food_items, water, beverage, activity).

Estratégia (MVP):
1. Normaliza o `target_hint` (remove acentos, lowercase, tokens).
2. Detecta o **kind** provável (food/water/beverage/activity) por keywords.
3. Detecta o **meal_slot** provável, se mencionado.
4. Pontua cada candidato: overlap de tokens no `normalized_name` +
   qualificador (meal_slot bate) + kind match.
5. Retorna 1 vencedor claro OU levanta `AmbiguousTarget` / `NoTargetFound`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.normalize import normalize_name
from app.models import (
    ActivityRecord,
    BeverageRecord,
    FoodItem,
    FoodRecord,
    WaterRecord,
)


class TargetKind(StrEnum):
    FOOD = "food"
    WATER = "water"
    BEVERAGE = "beverage"
    ACTIVITY = "activity"


_MEAL_SLOT_HINTS: dict[str, str] = {
    "cafe_da_manha": "breakfast",
    "cafe_manha": "breakfast",
    "cafedamanha": "breakfast",
    "breakfast": "breakfast",
    "manha": "breakfast",
    "almoco": "lunch",
    "lunch": "lunch",
    "lanche": "snack",
    "snack": "snack",
    "tarde": "snack",
    "jantar": "dinner",
    "dinner": "dinner",
    "noite": "dinner",
    "ceia": "other",
}

# Palavras que denunciam o tipo. Se aparecerem no hint, filtramos por tipo.
_KIND_HINTS: dict[str, TargetKind] = {
    "agua": TargetKind.WATER,
    "water": TargetKind.WATER,
    "cafe": TargetKind.BEVERAGE,
    "leite": TargetKind.BEVERAGE,
    "suco": TargetKind.BEVERAGE,
    "refrigerante": TargetKind.BEVERAGE,
    "cerveja": TargetKind.BEVERAGE,
    "vinho": TargetKind.BEVERAGE,
    "cha": TargetKind.BEVERAGE,
    "corrida": TargetKind.ACTIVITY,
    "corri": TargetKind.ACTIVITY,
    "caminhada": TargetKind.ACTIVITY,
    "caminhei": TargetKind.ACTIVITY,
    "musculacao": TargetKind.ACTIVITY,
    "treino": TargetKind.ACTIVITY,
    "bike": TargetKind.ACTIVITY,
    "ciclismo": TargetKind.ACTIVITY,
    "natacao": TargetKind.ACTIVITY,
    "yoga": TargetKind.ACTIVITY,
    "exercicio": TargetKind.ACTIVITY,
    "atividade": TargetKind.ACTIVITY,
}


@dataclass(slots=True)
class Candidate:
    kind: TargetKind
    entity_id: uuid.UUID
    entity: Any  # o próprio ORM object
    score: int


class MatchError(Exception):
    """Base para falhas de matching."""


class NoTargetFound(MatchError):
    def __init__(self, hint: str) -> None:
        super().__init__(hint)
        self.hint = hint


class AmbiguousTarget(MatchError):
    def __init__(self, hint: str, candidates: list[Candidate]) -> None:
        super().__init__(hint)
        self.hint = hint
        self.candidates = candidates


class TargetMatcher:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(
        self, *, day_log_id: uuid.UUID, target_hint: str
    ) -> Candidate:
        tokens = _tokenize(target_hint)
        if not tokens:
            raise NoTargetFound(target_hint)

        kind_filter = _detect_kind(tokens)
        meal_slot_filter = _detect_meal_slot(tokens)

        # Filtra tokens estruturais (kind e meal_slot) do conjunto que vai
        # scorear nomes, senão eles influenciam duas vezes.
        name_tokens = tokens - set(_MEAL_SLOT_HINTS.keys())

        candidates: list[Candidate] = []
        if kind_filter is None or kind_filter == TargetKind.FOOD:
            candidates.extend(
                await self._search_food(
                    day_log_id, name_tokens, meal_slot_filter
                )
            )
        if kind_filter is None or kind_filter == TargetKind.WATER:
            candidates.extend(
                await self._search_water(day_log_id, name_tokens)
            )
        if kind_filter is None or kind_filter == TargetKind.BEVERAGE:
            candidates.extend(
                await self._search_beverage(day_log_id, name_tokens)
            )
        if kind_filter is None or kind_filter == TargetKind.ACTIVITY:
            candidates.extend(
                await self._search_activity(day_log_id, name_tokens)
            )

        if not candidates:
            raise NoTargetFound(target_hint)

        candidates.sort(key=lambda c: c.score, reverse=True)
        top_score = candidates[0].score
        winners = [c for c in candidates if c.score == top_score]
        if len(winners) > 1:
            raise AmbiguousTarget(target_hint, winners)
        return winners[0]

    async def _search_food(
        self,
        day_log_id: uuid.UUID,
        tokens: set[str],
        meal_slot: str | None,
    ) -> list[Candidate]:
        stmt = (
            select(FoodItem, FoodRecord)
            .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
            .where(
                FoodRecord.day_log_id == day_log_id,
                FoodRecord.deleted_at.is_(None),
                FoodItem.deleted_at.is_(None),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        out: list[Candidate] = []
        for item, record in rows:
            score = _score(tokens, item.normalized_name)
            if score == 0:
                continue
            if meal_slot is not None and record.meal_slot == meal_slot:
                score += 5
            out.append(
                Candidate(
                    kind=TargetKind.FOOD,
                    entity_id=item.id,
                    entity=item,
                    score=score,
                )
            )
        return out

    async def _search_water(
        self, day_log_id: uuid.UUID, tokens: set[str]
    ) -> list[Candidate]:
        stmt = select(WaterRecord).where(
            WaterRecord.day_log_id == day_log_id,
            WaterRecord.deleted_at.is_(None),
        )
        rows = list((await self.session.execute(stmt)).scalars())
        # Água não tem detected_name; usamos "agua" implícito.
        implicit_name_score = _score(tokens, "agua")
        if implicit_name_score == 0:
            return []
        return [
            Candidate(
                kind=TargetKind.WATER,
                entity_id=r.id,
                entity=r,
                score=implicit_name_score,
            )
            for r in rows
        ]

    async def _search_beverage(
        self, day_log_id: uuid.UUID, tokens: set[str]
    ) -> list[Candidate]:
        stmt = select(BeverageRecord).where(
            BeverageRecord.day_log_id == day_log_id,
            BeverageRecord.deleted_at.is_(None),
        )
        rows = list((await self.session.execute(stmt)).scalars())
        out: list[Candidate] = []
        for r in rows:
            score = _score(tokens, r.normalized_name)
            if score == 0:
                continue
            out.append(
                Candidate(
                    kind=TargetKind.BEVERAGE,
                    entity_id=r.id,
                    entity=r,
                    score=score,
                )
            )
        return out

    async def _search_activity(
        self, day_log_id: uuid.UUID, tokens: set[str]
    ) -> list[Candidate]:
        stmt = select(ActivityRecord).where(
            ActivityRecord.day_log_id == day_log_id,
            ActivityRecord.deleted_at.is_(None),
        )
        rows = list((await self.session.execute(stmt)).scalars())
        out: list[Candidate] = []
        for r in rows:
            score = _score(tokens, r.normalized_name)
            if score == 0:
                # activity_type também vale (ex.: user diz "corrida", record
                # tem detected_name "Corrida 5km" mas activity_type=cardio_run).
                score = _score(tokens, r.activity_type)
                if score == 0:
                    continue
            out.append(
                Candidate(
                    kind=TargetKind.ACTIVITY,
                    entity_id=r.id,
                    entity=r,
                    score=score,
                )
            )
        return out


def _tokenize(hint: str) -> set[str]:
    normalized = normalize_name(hint)
    parts = [p for p in normalized.split("_") if p and len(p) > 1]
    return set(parts)


def _score(hint_tokens: set[str], candidate_name: str | None) -> int:
    if not candidate_name:
        return 0
    cand_tokens = set(candidate_name.split("_"))
    overlap = hint_tokens & cand_tokens
    return len(overlap)


def _detect_kind(tokens: set[str]) -> TargetKind | None:
    for token in tokens:
        kind = _KIND_HINTS.get(token)
        if kind is not None:
            return kind
    return None


def _detect_meal_slot(tokens: set[str]) -> str | None:
    for token in tokens:
        slot = _MEAL_SLOT_HINTS.get(token)
        if slot is not None:
            return slot
    return None
