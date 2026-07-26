"""SP-60 / SP-64 — ActivityCalculator determinístico (INV-1).

Testes unit puros: fórmula MET × weight_kg × (duration_minutes / 60).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.activity_calculator import ActivityCalculator


def test_cardio_run_moderate_typical():
    """Corrida moderada (MET 8.3) × 78 kg × 40 min = 431.6 kcal."""
    result = ActivityCalculator.compute(
        activity_type="cardio_run",
        intensity="moderate",
        duration_minutes=Decimal("40"),
        weight_kg=Decimal("78"),
    )
    assert result.met_value == Decimal("8.3")
    # 8.3 × 78 × (40/60) = 8.3 × 78 × 0.6667 = ~431.60
    assert result.kcal_burned == Decimal("431.60")
    assert result.calc_method == "mets_body_weight"
    assert result.reasons == []


def test_cardio_walk_light():
    """Caminhada leve (MET 2.8) × 70 kg × 30 min = 98 kcal."""
    result = ActivityCalculator.compute(
        activity_type="cardio_walk",
        intensity="light",
        duration_minutes=Decimal("30"),
        weight_kg=Decimal("70"),
    )
    assert result.met_value == Decimal("2.8")
    assert result.kcal_burned == Decimal("98.00")


def test_strength_defaults_to_moderate_via_lookup():
    """SP-62: strength com intensity 'moderate' usa MET 5.0."""
    result = ActivityCalculator.compute(
        activity_type="strength",
        intensity="moderate",
        duration_minutes=Decimal("60"),
        weight_kg=Decimal("80"),
    )
    assert result.met_value == Decimal("5.0")
    # 5 × 80 × 1 = 400
    assert result.kcal_burned == Decimal("400.00")


def test_unknown_activity_type_returns_zero_with_reason():
    result = ActivityCalculator.compute(
        activity_type="cirque_du_soleil",
        intensity="moderate",
        duration_minutes=Decimal("30"),
        weight_kg=Decimal("70"),
    )
    assert result.met_value is None
    assert result.kcal_burned == Decimal("0")
    assert result.calc_method == "llm_estimate"
    assert "unknown_activity_or_intensity" in result.reasons


def test_missing_duration_zeros_but_keeps_met():
    result = ActivityCalculator.compute(
        activity_type="cardio_run",
        intensity="moderate",
        duration_minutes=Decimal("0"),
        weight_kg=Decimal("78"),
    )
    assert result.kcal_burned == Decimal("0")
    assert result.met_value == Decimal("8.3")
    assert "missing_duration" in result.reasons


def test_missing_weight_zeros_but_keeps_met():
    result = ActivityCalculator.compute(
        activity_type="cardio_run",
        intensity="moderate",
        duration_minutes=Decimal("30"),
        weight_kg=Decimal("0"),
    )
    assert result.kcal_burned == Decimal("0")
    assert "missing_weight_kg" in result.reasons


def test_estimate_duration_from_distance_walk():
    """SP-63: 4 km caminhando a 5 km/h → 48 min."""
    duration = ActivityCalculator.estimate_duration_from_distance("cardio_walk", Decimal("4.0"))
    assert duration == Decimal("48.0000")


def test_estimate_duration_from_distance_run():
    """SP-63: 10 km correndo a 9 km/h → 66.67 min."""
    duration = ActivityCalculator.estimate_duration_from_distance("cardio_run", Decimal("10.0"))
    assert duration is not None
    assert duration.compare(Decimal("66.66")) == 1
    assert duration.compare(Decimal("66.67")) == -1


def test_estimate_duration_returns_none_for_unmapped_type():
    duration = ActivityCalculator.estimate_duration_from_distance(
        "cirque_du_soleil", Decimal("5.0")
    )
    assert duration is None


@pytest.mark.parametrize(
    "intensity,expected_met",
    [
        ("light", Decimal("6.0")),
        ("moderate", Decimal("8.3")),
        ("vigorous", Decimal("11.5")),
        ("unknown", Decimal("8.3")),
    ],
)
def test_cardio_run_all_intensities(intensity: str, expected_met: Decimal):
    result = ActivityCalculator.compute(
        activity_type="cardio_run",
        intensity=intensity,
        duration_minutes=Decimal("30"),
        weight_kg=Decimal("70"),
    )
    assert result.met_value == expected_met
