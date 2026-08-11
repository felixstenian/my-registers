"""Schemas de `nutrient_facts` (SP-33: PATCH para confirmar/editar;
SP-141/SP-142: POST manual + promoção opcional de item legado)."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NutrientFactPatch(BaseModel):
    """Campos parciais. Só sobrescreve os que vierem no payload.

    A ação de PATCH sempre marca `verified_by_user=true`, mesmo que nenhum
    valor mude — o usuário está atestando o cadastro.
    """

    kcal: float | None = Field(default=None, ge=0, le=10000)
    protein_g: float | None = Field(default=None, ge=0, le=1000)
    carbs_g: float | None = Field(default=None, ge=0, le=1000)
    fat_g: float | None = Field(default=None, ge=0, le=1000)
    fiber_g: float | None = Field(default=None, ge=0, le=1000)
    sodium_mg: float | None = Field(default=None, ge=0, le=100000)
    calcium_mg: float | None = Field(default=None, ge=0, le=100000)
    iron_mg: float | None = Field(default=None, ge=0, le=10000)
    potassium_mg: float | None = Field(default=None, ge=0, le=100000)
    serving_grams: float | None = Field(default=None, gt=0, le=5000)


class NutrientFactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_name: str
    brand: str | None
    source: str
    basis: str
    barcode: str | None
    verified_by_user: bool
    kcal: float | None
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    fiber_g: float | None
    sodium_mg: float | None
    calcium_mg: float | None
    iron_mg: float | None
    potassium_mg: float | None


_CANONICAL_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")


class ManualNutrientFactIn(BaseModel):
    """SP-141 — cadastro manual de fact sem foto de rótulo.

    Todos os limites de campo espelham `NutrientFactPatch` para consistência.
    """

    canonical_name: str = Field(min_length=2, max_length=120)
    display_name: str | None = Field(default=None, max_length=200)
    brand: str | None = Field(default=None, max_length=120)
    basis: Literal["per_100g", "per_100ml"]
    kcal: float = Field(ge=0, le=10000)
    protein_g: float = Field(default=0, ge=0, le=1000)
    carbs_g: float = Field(default=0, ge=0, le=1000)
    fat_g: float = Field(default=0, ge=0, le=1000)
    fiber_g: float | None = Field(default=None, ge=0, le=1000)
    sodium_mg: float | None = Field(default=None, ge=0, le=100000)
    calcium_mg: float | None = Field(default=None, ge=0, le=100000)
    iron_mg: float | None = Field(default=None, ge=0, le=10000)
    potassium_mg: float | None = Field(default=None, ge=0, le=100000)
    serving_grams: float | None = Field(default=None, gt=0, le=5000)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    # SP-142: se presente, promove o food_item legado após criar o fact.
    # UUID validado por Pydantic. Erros de promoção não falham o cadastro.
    promote_food_item_id: uuid.UUID | None = None

    @field_validator("canonical_name")
    @classmethod
    def _validate_canonical(cls, v: str) -> str:
        if not _CANONICAL_NAME_PATTERN.match(v):
            raise ValueError(
                "canonical_name deve conter apenas [a-z0-9_] (ex.: pao_de_queijo_congelado)"
            )
        return v

    @field_validator("aliases")
    @classmethod
    def _dedupe_aliases(cls, v: list[str]) -> list[str]:
        # Aliases sempre lowercased + deduplicated + strip vazio.
        seen: set[str] = set()
        out: list[str] = []
        for a in v:
            s = a.strip().lower()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out


class ManualNutrientFactOut(NutrientFactOut):
    """Resposta do POST /manual: fact criado + eventual warning de promoção."""

    # Se `promote_food_item_id` foi informado no request e a promoção falhou,
    # devolvemos o motivo aqui. Fact sempre criado (não fazemos rollback
    # por causa do warning).
    promotion_warning: str | None = None
    promoted_item_id: uuid.UUID | None = None
