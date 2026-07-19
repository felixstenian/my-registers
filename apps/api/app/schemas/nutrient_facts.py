"""Schemas de `nutrient_facts` (SP-33: PATCH para confirmar/editar)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


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
