"""JSON schema da tool `record_intent` (Const. §7, INV-9).

Definido separadamente para poder ser cacheado no prompt caching da Anthropic
(`cache_control: ephemeral`) sem quebrar por diferença de whitespace entre
turnos. Referência: `app_plan.md` §8.2.
"""

from __future__ import annotations

from typing import Any

RECORD_INTENT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "user_text_summary", "confidence"],
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
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
                "workout_next_exercise",
                "clarify",
                "unknown",
            ],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "user_text_summary": {"type": "string"},
        "needs_clarification": {"type": "boolean"},
        "clarification_question": {"type": ["string", "null"]},
        "occurred_at_hint": {"type": ["string", "null"]},
        "meal_slot": {
            "type": ["string", "null"],
            "enum": [
                None,
                "breakfast",
                "lunch",
                "snack",
                "dinner",
                "other",
                "unspecified",
            ],
        },
        "food_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["detected_name", "confidence"],
                "properties": {
                    "detected_name": {"type": "string"},
                    "normalized_name": {"type": ["string", "null"]},
                    "brand": {"type": ["string", "null"]},
                    "quantity": {"type": ["number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "grams_estimate": {"type": ["number", "null"]},
                    "ml_estimate": {"type": ["number", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "is_estimate": {"type": "boolean"},
                },
            },
        },
        "water": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["volume_ml", "confidence"],
            "properties": {
                "volume_ml": {"type": "number", "minimum": 1},
                "confidence": {"type": "number"},
            },
        },
        "beverage": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["detected_name", "volume_ml", "confidence"],
            "properties": {
                "detected_name": {"type": "string"},
                "brand": {"type": ["string", "null"]},
                "volume_ml": {"type": "number", "minimum": 1},
                "beverage_kind": {"type": "string", "enum": ["other"]},
                "confidence": {"type": "number"},
            },
        },
        "activity": {
            "type": ["object", "null"],
            "additionalProperties": False,
            # Sonnet costuma incluir tudo mesmo sem `required`; Haiku 4.5 é
            # mais preguiçoso e omite `confidence`/`intensity` — daí o retry
            # semântico esgotava. Marcar como required deixa qualquer modelo
            # ciente do contrato.
            "required": [
                "detected_name",
                "activity_type",
                "duration_minutes",
                "intensity",
                "confidence",
            ],
            "properties": {
                "detected_name": {"type": "string"},
                "activity_type": {"type": "string"},
                "duration_minutes": {"type": "number", "minimum": 1},
                "distance_km": {"type": ["number", "null"]},
                "intensity": {
                    "type": "string",
                    "enum": ["light", "moderate", "vigorous", "unknown"],
                },
                "confidence": {"type": "number"},
                "kcal_burned_reported": {
                    "type": ["number", "null"],
                    "minimum": 0,
                    "maximum": 10000,
                    "description": (
                        "Quando a mensagem/foto trouxer o valor total de calorias "
                        "já calculado pelo dispositivo (smartwatch, esteira, app de "
                        "corrida), leia esse número aqui em vez de deixar o backend "
                        "recalcular por MET. Só preencha se estiver visível/dito."
                    ),
                },
            },
        },
        "correction": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["target_hint", "confidence"],
            "properties": {
                "target_hint": {"type": "string"},
                "changes": {"type": "object"},
                "confidence": {"type": "number"},
            },
        },
        "deletion": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["target_hint", "confidence"],
            "properties": {
                "target_hint": {"type": "string"},
                "confidence": {"type": "number"},
            },
        },
        "nutrition_label": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["product_name", "basis"],
            "properties": {
                "product_name": {"type": "string"},
                "brand": {"type": ["string", "null"]},
                "barcode": {"type": ["string", "null"]},
                "basis": {
                    "type": "string",
                    "enum": ["per_100g", "per_100ml", "per_serving"],
                },
                "serving_size_g": {"type": ["number", "null"]},
                "serving_size_ml": {"type": ["number", "null"]},
                "servings_per_pack": {"type": ["number", "null"]},
                "kcal": {"type": ["number", "null"]},
                "protein_g": {"type": ["number", "null"]},
                "carbs_g": {"type": ["number", "null"]},
                "sugars_g": {"type": ["number", "null"]},
                "added_sugars_g": {"type": ["number", "null"]},
                "fat_g": {"type": ["number", "null"]},
                "saturated_fat_g": {"type": ["number", "null"]},
                "trans_fat_g": {"type": ["number", "null"]},
                "fiber_g": {"type": ["number", "null"]},
                "sodium_mg": {"type": ["number", "null"]},
                "calcium_mg": {"type": ["number", "null"]},
                "iron_mg": {"type": ["number", "null"]},
                "potassium_mg": {"type": ["number", "null"]},
                "confidence_per_field": {"type": "object"},
                "also_consumed": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "properties": {
                        "quantity": {"type": "number"},
                        "unit": {"type": "string"},
                        "grams": {"type": ["number", "null"]},
                        "ml": {"type": ["number", "null"]},
                        "servings": {"type": ["number", "null"]},
                    },
                },
            },
        },
        "profile_update": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "weight_kg": {"type": ["number", "null"], "minimum": 0, "maximum": 500},
                "height_cm": {"type": ["number", "null"], "minimum": 0, "maximum": 300},
                "birthdate": {
                    "type": ["string", "null"],
                    "description": "Data ISO 8601 YYYY-MM-DD.",
                },
                "sex": {
                    "type": ["string", "null"],
                    "enum": [None, "m", "f", "o", "n"],
                    "description": "m=masculino, f=feminino, o=outro, n=prefere não dizer.",
                },
            },
        },
        "workout_start": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["workout_type"],
            "properties": {
                "workout_type": {
                    "type": "string",
                    "enum": [
                        "push",
                        "pull",
                        "legs",
                        "upper",
                        "lower",
                        "full_body",
                        "cardio",
                        "other",
                    ],
                },
                "detected_name": {"type": ["string", "null"]},
                "template_id": {"type": ["string", "null"]},
            },
        },
        "workout_add_exercise": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["exercise_name"],
            "properties": {
                "exercise_name": {"type": "string"},
            },
        },
        "workout_log_set": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["reps"],
            "properties": {
                "weight_kg": {"type": ["number", "null"], "minimum": 0, "maximum": 1000},
                "reps": {"type": "integer", "minimum": 1, "maximum": 1000},
                "notes": {"type": ["string", "null"]},
            },
        },
        "workout_end": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {},
        },
        "workout_next_exercise": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {},
        },
        "workout_history": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["exercise_name"],
            "properties": {
                "exercise_name": {"type": "string"},
            },
        },
        "workout_template": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["name", "workout_type"],
            "properties": {
                "name": {"type": "string"},
                "workout_type": {
                    "type": "string",
                    "enum": [
                        "push",
                        "pull",
                        "legs",
                        "upper",
                        "lower",
                        "full_body",
                        "cardio",
                        "other",
                    ],
                },
                "muscle_groups": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "exercises": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["exercise_name"],
                        "properties": {
                            "exercise_name": {"type": "string"},
                            "target_sets": {
                                "type": ["integer", "null"],
                                "minimum": 1,
                                "maximum": 100,
                            },
                            "target_reps": {
                                "type": ["integer", "null"],
                                "minimum": 1,
                                "maximum": 1000,
                            },
                        },
                    },
                },
            },
        },
        "workout_correct": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["target_hint"],
            "properties": {
                "target_hint": {"type": "string"},
                "weight_kg": {"type": ["number", "null"], "minimum": 0, "maximum": 1000},
                "reps": {"type": ["integer", "null"], "minimum": 1, "maximum": 1000},
                "notes": {"type": ["string", "null"]},
            },
        },
    },
}


RECORD_INTENT_TOOL: dict[str, Any] = {
    "name": "record_intent",
    "description": (
        "Registra a intenção do usuário e os itens estruturados extraídos "
        "da mensagem (texto e/ou imagens). O backend faz todos os cálculos "
        "nutricionais; esta tool é o único caminho de retorno de dados."
    ),
    "input_schema": RECORD_INTENT_INPUT_SCHEMA,
}
