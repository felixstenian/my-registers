"""Contrato Pydantic para a resposta da LLM via `tool_use` (Const. §7, INV-9).

Ordem canônica em `app_plan.md` §8. Qualquer texto livre da LLM (fora de
`tool_use.input`) é descartado. Sub-modelos são usados para os intents que
carregam payload; para `clarify`/`unknown`/`query_day`/etc, os campos ficam
`None` e o backend usa `user_text_summary` / `clarification_question`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Intent = Literal[
    "log_food",
    "log_nutrition_label",
    "log_water",
    "log_beverage",
    "log_activity",
    "correct_record",
    "delete_record",
    "query_day",
    "close_day",
    "weekly_summary",
    "set_profile",
    "clarify",
    "unknown",
]

Sex = Literal["m", "f", "o", "n"]

MealSlot = Literal["breakfast", "lunch", "snack", "dinner", "other", "unspecified"]

Confidence = Field(ge=0, le=1)


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FoodItemIn(_StrictBase):
    detected_name: str
    normalized_name: str | None = None
    brand: str | None = None
    quantity: float | None = None
    unit: str | None = None
    grams_estimate: float | None = None
    ml_estimate: float | None = None
    confidence: float = Confidence
    is_estimate: bool = False


class WaterIn(_StrictBase):
    volume_ml: float = Field(ge=1)
    confidence: float = Confidence


class BeverageIn(_StrictBase):
    detected_name: str
    brand: str | None = None
    volume_ml: float = Field(ge=1)
    beverage_kind: Literal["other"] = "other"
    confidence: float = Confidence


class ActivityIn(_StrictBase):
    detected_name: str
    activity_type: str
    duration_minutes: float = Field(ge=1)
    distance_km: float | None = None
    intensity: Literal["light", "moderate", "vigorous", "unknown"] = "unknown"
    confidence: float = Confidence
    # Quando o usuário anexa print de smartwatch/app com kcal já calculado,
    # a LLM extrai esse número aqui. Se presente, é fonte de verdade
    # (`calc_method='user_manual'`) — sobrescreve o cálculo MET × weight.
    kcal_burned_reported: float | None = Field(default=None, ge=0, le=10000)


class CorrectionIn(_StrictBase):
    target_hint: str
    changes: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    confidence: float = Confidence


class DeletionIn(_StrictBase):
    target_hint: str
    confidence: float = Confidence


class NutritionLabelAlsoConsumed(_StrictBase):
    quantity: float
    unit: str
    grams: float | None = None
    ml: float | None = None
    servings: float | None = None


class NutritionLabelIn(_StrictBase):
    product_name: str
    brand: str | None = None
    barcode: str | None = None
    basis: Literal["per_100g", "per_100ml", "per_serving"]
    serving_size_g: float | None = None
    serving_size_ml: float | None = None
    servings_per_pack: float | None = None
    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    sugars_g: float | None = None
    added_sugars_g: float | None = None
    fat_g: float | None = None
    saturated_fat_g: float | None = None
    trans_fat_g: float | None = None
    fiber_g: float | None = None
    sodium_mg: float | None = None
    calcium_mg: float | None = None
    iron_mg: float | None = None
    potassium_mg: float | None = None
    confidence_per_field: dict[str, float] = Field(default_factory=dict)
    also_consumed: NutritionLabelAlsoConsumed | None = None

    @model_validator(mode="after")
    def _serving_needs_size(self) -> NutritionLabelIn:
        if self.basis == "per_serving" and not (self.serving_size_g or self.serving_size_ml):
            raise ValueError("basis=per_serving requer serving_size_g ou serving_size_ml")
        return self


class ProfileUpdateIn(_StrictBase):
    """Atualização de perfil por chat (SP-61 e futuros).

    Pelo menos um campo precisa estar preenchido — validado no service, não
    no Pydantic, para que a LLM possa mandar um envelope vazio de forma
    controlada e o backend sinalize `nothing_to_update`.
    """

    weight_kg: float | None = Field(default=None, gt=0, le=500)
    height_cm: float | None = Field(default=None, gt=0, le=300)
    birthdate: date | None = None
    sex: Sex | None = None


class LLMEnvelope(_StrictBase):
    intent: Intent
    confidence: float = Confidence
    user_text_summary: str
    needs_clarification: bool = False
    clarification_question: str | None = None
    occurred_at_hint: datetime | None = None
    meal_slot: MealSlot | None = None
    food_items: list[FoodItemIn] = Field(default_factory=list)
    water: WaterIn | None = None
    beverage: BeverageIn | None = None
    activity: ActivityIn | None = None
    correction: CorrectionIn | None = None
    deletion: DeletionIn | None = None
    nutrition_label: NutritionLabelIn | None = None
    profile_update: ProfileUpdateIn | None = None
