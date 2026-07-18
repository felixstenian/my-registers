"""ActivityCalculator — kcal_burned deterministicamente.

Fórmula clássica MET (SP-60/SP-64):
    kcal = met × weight_kg × (duration_minutes / 60)

Tabela de METs por `activity_type` × `intensity` cobre os casos mais
comuns. Se o par não estiver mapeado, retornamos `None` (o service
decide se cai em `llm_estimate` ou pede clarify).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

_MET_TABLE: dict[tuple[str, str], Decimal] = {
    # corrida
    ("cardio_run", "light"): Decimal("6.0"),
    ("cardio_run", "moderate"): Decimal("8.3"),
    ("cardio_run", "vigorous"): Decimal("11.5"),
    ("cardio_run", "unknown"): Decimal("8.3"),
    # caminhada
    ("cardio_walk", "light"): Decimal("2.8"),
    ("cardio_walk", "moderate"): Decimal("3.8"),
    ("cardio_walk", "vigorous"): Decimal("5.0"),
    ("cardio_walk", "unknown"): Decimal("3.5"),
    # bike
    ("bike", "light"): Decimal("4.0"),
    ("bike", "moderate"): Decimal("6.8"),
    ("bike", "vigorous"): Decimal("10.0"),
    ("bike", "unknown"): Decimal("6.0"),
    # natação
    ("swim", "light"): Decimal("4.0"),
    ("swim", "moderate"): Decimal("7.0"),
    ("swim", "vigorous"): Decimal("10.0"),
    ("swim", "unknown"): Decimal("6.0"),
    # musculação / strength — SP-62 default moderate=5.0
    ("strength", "light"): Decimal("3.5"),
    ("strength", "moderate"): Decimal("5.0"),
    ("strength", "vigorous"): Decimal("6.0"),
    ("strength", "unknown"): Decimal("5.0"),
    # yoga / mobility
    ("yoga", "light"): Decimal("2.0"),
    ("yoga", "moderate"): Decimal("3.0"),
    ("yoga", "vigorous"): Decimal("4.0"),
    ("yoga", "unknown"): Decimal("2.5"),
    # elíptico / cardio genérico
    ("cardio", "light"): Decimal("4.0"),
    ("cardio", "moderate"): Decimal("6.5"),
    ("cardio", "vigorous"): Decimal("9.0"),
    ("cardio", "unknown"): Decimal("6.0"),
}

# Velocidades médias em km/h para estimar duração a partir de distância (SP-63).
_SPEED_KMH: dict[str, Decimal] = {
    "cardio_walk": Decimal("5.0"),
    "cardio_run": Decimal("9.0"),
    "bike": Decimal("20.0"),
    "swim": Decimal("3.5"),
    "cardio": Decimal("7.0"),
}


@dataclass(slots=True)
class ActivityComputation:
    met_value: Decimal | None
    kcal_burned: Decimal
    calc_method: str
    reasons: list[str]


class ActivityCalculator:
    @staticmethod
    def lookup_met(activity_type: str, intensity: str) -> Decimal | None:
        return _MET_TABLE.get((activity_type, intensity))

    @staticmethod
    def estimate_duration_from_distance(
        activity_type: str, distance_km: Decimal
    ) -> Decimal | None:
        """SP-63: sem duração mas com distância → estimar por velocidade média."""
        speed = _SPEED_KMH.get(activity_type)
        if speed is None or speed <= 0:
            return None
        return (distance_km / speed) * Decimal("60")

    @classmethod
    def compute(
        cls,
        *,
        activity_type: str,
        intensity: str,
        duration_minutes: Decimal,
        weight_kg: Decimal,
    ) -> ActivityComputation:
        met = cls.lookup_met(activity_type, intensity)
        if met is None:
            return ActivityComputation(
                met_value=None,
                kcal_burned=Decimal("0"),
                calc_method="llm_estimate",
                reasons=["unknown_activity_or_intensity"],
            )
        if duration_minutes <= 0:
            return ActivityComputation(
                met_value=met,
                kcal_burned=Decimal("0"),
                calc_method="mets_body_weight",
                reasons=["missing_duration"],
            )
        if weight_kg <= 0:
            return ActivityComputation(
                met_value=met,
                kcal_burned=Decimal("0"),
                calc_method="mets_body_weight",
                reasons=["missing_weight_kg"],
            )
        hours = duration_minutes / Decimal("60")
        kcal = (met * weight_kg * hours).quantize(Decimal("0.01"))
        return ActivityComputation(
            met_value=met,
            kcal_burned=kcal,
            calc_method="mets_body_weight",
            reasons=[],
        )
