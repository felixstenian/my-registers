"""SP-20/SP-23 — NutritionCalculator determinístico (INV-1).

Testes de UNIT puros: sem DB, sem LLM. Cobrem casos de basis per_100g,
per_100ml, falta de hit, falta de quantidade, valores parciais.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.integrations.nutrition.catalog import CatalogHit
from app.services.nutrition_calculator import ComputedNutrition, NutritionCalculator


def _hit(
    *,
    basis: str = "per_100g",
    kcal: str | None = "124.0",
    protein: str | None = "2.5",
    carbs: str | None = "25.8",
    fat: str | None = "1.0",
    sodium: str | None = "1.0",
) -> CatalogHit:
    return CatalogHit(
        fact_id="00000000-0000-0000-0000-000000000000",
        canonical_name="teste",
        basis=basis,
        kcal=Decimal(kcal) if kcal else None,
        protein_g=Decimal(protein) if protein else None,
        carbs_g=Decimal(carbs) if carbs else None,
        fat_g=Decimal(fat) if fat else None,
        fiber_g=Decimal("1.0"),
        sodium_mg=Decimal(sodium) if sodium else None,
        calcium_mg=Decimal("4"),
        iron_mg=Decimal("0.14"),
        potassium_mg=Decimal("26"),
        source="TBCA_2023",
        verified_by_user=False,
    )


def test_per_100g_scales_by_grams():
    r = NutritionCalculator.compute(hit=_hit(), grams=Decimal("150"), ml=None)
    assert r.kcal == Decimal("186.00")
    assert r.protein_g == Decimal("3.75")
    assert r.carbs_g == Decimal("38.70")
    assert r.fat_g == Decimal("1.50")
    assert r.reasons == []


def test_per_100ml_scales_by_ml():
    hit = _hit(basis="per_100ml", kcal="884.0", protein="0", carbs="0", fat="100.0")
    r = NutritionCalculator.compute(hit=hit, grams=None, ml=Decimal("10"))
    assert r.kcal == Decimal("88.40")
    assert r.fat_g == Decimal("10.00")


def test_no_hit_returns_zeros_with_reason():
    r = NutritionCalculator.compute(hit=None, grams=Decimal("100"), ml=None)
    assert r.kcal == Decimal("0")
    assert r == ComputedNutrition.zeros("no_catalog_hit")


def test_missing_grams_returns_zeros_with_reason():
    r = NutritionCalculator.compute(hit=_hit(), grams=None, ml=None)
    assert r.kcal == Decimal("0")
    assert "missing_grams" in r.reasons


def test_missing_ml_for_liquid_returns_zeros_with_reason():
    hit = _hit(basis="per_100ml")
    r = NutritionCalculator.compute(hit=hit, grams=Decimal("100"), ml=None)
    assert r.kcal == Decimal("0")
    assert "missing_ml" in r.reasons


def test_zero_or_negative_grams_treated_as_missing():
    r = NutritionCalculator.compute(hit=_hit(), grams=Decimal("0"), ml=None)
    assert r.kcal == Decimal("0")


def test_partial_fields_do_not_crash():
    hit = _hit(kcal=None, protein=None, sodium=None)
    r = NutritionCalculator.compute(hit=hit, grams=Decimal("200"), ml=None)
    assert r.kcal == Decimal("0")
    assert r.protein_g == Decimal("0")
    assert r.sodium_mg == Decimal("0")
    # os campos preenchidos continuam sendo escalados
    assert r.carbs_g == Decimal("51.60")


def test_rounds_to_two_decimal_places():
    hit = _hit(kcal="123.456")
    r = NutritionCalculator.compute(hit=hit, grams=Decimal("77"), ml=None)
    # 123.456 * 0.77 = 95.06112 → 95.06
    assert r.kcal == Decimal("95.06")


def test_invalid_basis_returns_zeros():
    hit = _hit(basis="per_serving")  # não é aceito no MVP
    r = NutritionCalculator.compute(hit=hit, grams=Decimal("100"), ml=None)
    assert r.kcal == Decimal("0")
    assert "unknown_basis" in r.reasons


@pytest.mark.parametrize(
    "grams,expected_kcal",
    [
        (Decimal("50"), Decimal("62.00")),
        (Decimal("100"), Decimal("124.00")),
        (Decimal("250"), Decimal("310.00")),
    ],
)
def test_various_gram_amounts(grams: Decimal, expected_kcal: Decimal):
    r = NutritionCalculator.compute(hit=_hit(), grams=grams, ml=None)
    assert r.kcal == expected_kcal
