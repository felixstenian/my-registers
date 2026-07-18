"""NutritionCalculator — computa kcal/macros/micros determinísticamente.

Const. Art. II §5 e INV-1: LLM não aparece aqui. Chame-me com um
`CatalogHit` (valores por 100g/ml) e quantidade em gramas ou ml, e eu
devolvo o valor para o item. Se falta hit ou falta quantidade, devolvo
zeros e uma lista de razões.

Cobertura mínima 90% (plan.md §5.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.integrations.nutrition.catalog import CatalogHit

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


@dataclass(slots=True)
class ComputedNutrition:
    kcal: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    fiber_g: Decimal
    sodium_mg: Decimal
    calcium_mg: Decimal
    iron_mg: Decimal
    potassium_mg: Decimal
    reasons: list[str]  # 'no_catalog_hit', 'missing_quantity', etc.

    @classmethod
    def zeros(cls, *reasons: str) -> ComputedNutrition:
        return cls(
            kcal=_ZERO,
            protein_g=_ZERO,
            carbs_g=_ZERO,
            fat_g=_ZERO,
            fiber_g=_ZERO,
            sodium_mg=_ZERO,
            calcium_mg=_ZERO,
            iron_mg=_ZERO,
            potassium_mg=_ZERO,
            reasons=list(reasons),
        )


def _mul(hit_value: Decimal | None, factor: Decimal) -> Decimal:
    if hit_value is None:
        return _ZERO
    return (Decimal(hit_value) * factor).quantize(Decimal("0.01"))


class NutritionCalculator:
    @staticmethod
    def compute(
        *,
        hit: CatalogHit | None,
        grams: Decimal | None,
        ml: Decimal | None,
    ) -> ComputedNutrition:
        if hit is None:
            return ComputedNutrition.zeros("no_catalog_hit")

        if hit.basis == "per_100g":
            amount = grams
            unit_name = "grams"
        elif hit.basis == "per_100ml":
            amount = ml
            unit_name = "ml"
        else:
            return ComputedNutrition.zeros("unknown_basis")

        if amount is None or amount <= 0:
            return ComputedNutrition.zeros(f"missing_{unit_name}")

        factor = Decimal(amount) / _HUNDRED

        return ComputedNutrition(
            kcal=_mul(hit.kcal, factor),
            protein_g=_mul(hit.protein_g, factor),
            carbs_g=_mul(hit.carbs_g, factor),
            fat_g=_mul(hit.fat_g, factor),
            fiber_g=_mul(hit.fiber_g, factor),
            sodium_mg=_mul(hit.sodium_mg, factor),
            calcium_mg=_mul(hit.calcium_mg, factor),
            iron_mg=_mul(hit.iron_mg, factor),
            potassium_mg=_mul(hit.potassium_mg, factor),
            reasons=[],
        )
