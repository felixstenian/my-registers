"""Contrato Pydantic para a resposta da LLM via `tool_use` (Const. §7, INV-9).

Ordem canônica em `app_plan.md` §8. Qualquer texto livre da LLM (fora de
`tool_use.input`) é descartado. Sub-modelos são usados para os intents que
carregam payload; para `clarify`/`unknown`/`query_day`/etc, os campos ficam
`None` e o backend usa `user_text_summary` / `clarification_question`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    "workout_start",
    "workout_add_exercise",
    "workout_log_set",
    "workout_end",
    "workout_history",
    "workout_register_template",
    "workout_correct",
    "clarify",
    "unknown",
]

Sex = Literal["m", "f", "o", "n"]

MealSlot = Literal["breakfast", "lunch", "snack", "dinner", "other", "unspecified"]

Confidence = Field(ge=0, le=1)


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Payloads de registro (`FoodItemIn`, `BeverageIn`, `ActivityIn`) usam
# `extra="ignore"`: a LLM tende a inventar campos comuns de contexto
# (`pace`, `heart_rate_avg`, `calories`, `sugars_g`, etc.) que **não**
# consumimos, mas rejeitá-los levaria a `validation_exhausted` — o
# assistant cairia no fallback genérico "Não consegui interpretar".
# Fields conhecidos ainda são validados normalmente; extras são
# silenciosamente descartados.
class _LenientBase(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FoodItemIn(_LenientBase):
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


class BeverageIn(_LenientBase):
    detected_name: str
    brand: str | None = None
    volume_ml: float = Field(ge=1)
    beverage_kind: Literal["other"] = "other"
    confidence: float = Confidence


_INTENSITY_ALIASES: dict[str, str] = {
    # pt-BR (feminino e masculino) → canônico. Normalizado sem acento.
    "leve": "light",
    "baixa": "light",
    "baixo": "light",
    "moderada": "moderate",
    "moderado": "moderate",
    "media": "moderate",
    "medio": "moderate",
    "intensa": "vigorous",
    "intenso": "vigorous",
    "alta": "vigorous",
    "alto": "vigorous",
    "forte": "vigorous",
    "vigorosa": "vigorous",
    "vigoroso": "vigorous",
    "pesada": "vigorous",
    "pesado": "vigorous",
    # Inglês minúsculo direto (para caso do LLM devolver capitalizado).
    "light": "light",
    "moderate": "moderate",
    "vigorous": "vigorous",
    "unknown": "unknown",
}


def _normalize_intensity(value: object) -> object:
    """Aceita pt-BR e maiúsculas antes da validação do Literal.

    Regressão: LLM às vezes emite "moderada" (pt-BR) mesmo com prompt em
    inglês — o Literal do Pydantic rejeita e o retry semântico esgota,
    resultando em "Não consegui interpretar sua mensagem agora." O fix
    normaliza os aliases mais comuns aqui, antes da validação.
    """
    if not isinstance(value, str):
        return value
    import unicodedata

    stripped = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", value.strip().lower())
        if not unicodedata.combining(ch)
    )
    return _INTENSITY_ALIASES.get(stripped, value)


class ActivityIn(_LenientBase):
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

    @field_validator("intensity", mode="before")
    @classmethod
    def _accept_ptbr_intensity(cls, value):
        return _normalize_intensity(value)

    @field_validator("duration_minutes", mode="before")
    @classmethod
    def _coerce_duration(cls, value):
        """LLM ocasionalmente emite duração como string ("40") ou dict
        com unidade. Aceita string numérica; deixa Pydantic falhar em
        outros casos."""
        if isinstance(value, str):
            try:
                return float(value.strip().split()[0])
            except (ValueError, IndexError):
                return value
        return value


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


WorkoutType = Literal[
    "push",
    "pull",
    "legs",
    "upper",
    "lower",
    "full_body",
    "cardio",
    "other",
]


class WorkoutStartIn(_LenientBase):
    """SP-120. `workout_type` no enum canônico; `detected_name` livre
    (copy do usuário). `template_id` (SP-178/INV-20): UUID do template
    do fluxo guiado — o frontend o injeta quando o usuário escolhe um
    template no picker (o LLM não conhece UUIDs; nunca deve inventá-lo).
    Sem `template_id` → sessão livre (SP-120)."""

    workout_type: WorkoutType
    detected_name: str | None = None
    template_id: uuid.UUID | None = None


class WorkoutExerciseIn(_LenientBase):
    """SP-121. Nome do exercício como dito pelo usuário; `normalized_name`
    é derivado no backend."""

    exercise_name: str


class WorkoutSetIn(_LenientBase):
    """SP-122. Peso/reps de uma série. `weight_kg=None` → barra olímpica
    (20kg default, resolvido no backend). `reps` obrigatório."""

    weight_kg: float | None = Field(default=None, gt=0, le=1000)
    reps: int = Field(gt=0, le=1000)
    notes: str | None = None


class WorkoutEndIn(_LenientBase):
    """SP-124. Encerramento explícito da sessão — sem payload extra."""


class WorkoutHistoryQueryIn(_LenientBase):
    """SP-127. Consulta de histórico por exercício. `exercise_name`
    obrigatório; se ausente o backend emite `clarify`."""

    exercise_name: str


class WorkoutTemplateExerciseIn(_LenientBase):
    """SP-171. Exercício-alvo de um treino reutilizável. `target_sets`/
    `target_reps` opcionais (plano sugerido); `normalized_name` é derivado
    no backend."""

    exercise_name: str
    target_sets: int | None = Field(default=None, gt=0, le=100)
    target_reps: int | None = Field(default=None, gt=0, le=1000)


class WorkoutTemplateIn(_LenientBase):
    """SP-171. Cadastro de treino reutilizável por texto (intent
    `workout_register_template`).

    `workout_type` no enum canônico; `name` é um rótulo curto do treino
    (ex. "Peito e tríceps"); `muscle_groups` opcional (agrupamento muscular
    para musculação, ex. ["peito", "ombro", "triceps"]); `exercises` é a
    lista de exercícios com séries/reps sugeridos.
    """

    name: str
    workout_type: WorkoutType
    muscle_groups: list[str] | None = None
    exercises: list[WorkoutTemplateExerciseIn] = Field(default_factory=list)


class WorkoutCorrectSetIn(_LenientBase):
    """SP-175. Correção de um `workout_set` por chat (intent `workout_correct`).
    Identificado por descrição livre (`target_hint`) — o backend resolve qual
    vez/série — e campos opcionais a corrigir."""

    target_hint: str
    weight_kg: float | None = Field(default=None, gt=0, le=1000)
    reps: int | None = Field(default=None, gt=0, le=1000)
    notes: str | None = None


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
    workout_start: WorkoutStartIn | None = None
    workout_add_exercise: WorkoutExerciseIn | None = None
    workout_log_set: WorkoutSetIn | None = None
    workout_end: WorkoutEndIn | None = None
    workout_history: WorkoutHistoryQueryIn | None = None
    workout_template: WorkoutTemplateIn | None = None
    workout_correct: WorkoutCorrectSetIn | None = None
