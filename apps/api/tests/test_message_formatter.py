"""SP-118 — testes unitários do formato tabular de assistant messages.

Testa as regras de formatação pt-BR, prefixo `≈`, ordenação e conteúdo
das duas tabelas para cada intent (log_food/water/beverage/activity).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services import message_formatter as mf

DISCLAIMER = (
    "As estimativas nutricionais são aproximações e não substituem "
    "acompanhamento médico ou nutricional."
)


@dataclass
class FakeSnapshot:
    kcal_in: Decimal = Decimal(0)
    kcal_out: Decimal = Decimal(0)
    kcal_balance: Decimal = Decimal(0)
    protein_g: Decimal = Decimal(0)
    carbs_g: Decimal = Decimal(0)
    fat_g: Decimal = Decimal(0)
    fiber_g: Decimal = Decimal(0)
    water_ml: int = 0
    other_liquids_ml: int = 0


def _snap(**overrides) -> FakeSnapshot:
    for k, v in list(overrides.items()):
        if isinstance(v, (int, float)) and k not in {"water_ml", "other_liquids_ml"}:
            overrides[k] = Decimal(str(v))
    return FakeSnapshot(**overrides)


# ---------------------------------------------------------------------------
# Formatação pt-BR
# ---------------------------------------------------------------------------


def test_fmt_int_uses_dot_thousand():
    assert mf._fmt_int(1200) == "1.200"
    assert mf._fmt_int(1234567) == "1.234.567"
    assert mf._fmt_int(42) == "42"
    assert mf._fmt_int(None) == "0"


def test_fmt_dec_uses_comma_decimal():
    assert mf._fmt_dec(46.7) == "46,7"
    assert mf._fmt_dec(Decimal("977.35"), digits=2) == "977,35"
    # milhar + decimal
    assert mf._fmt_dec(Decimal("1234.5"), digits=1) == "1.234,5"


def test_fmt_kcal_prefix_only_when_approx():
    assert mf._fmt_kcal(977, approx=False) == "977 kcal"
    assert mf._fmt_kcal(977, approx=True) == "≈ 977 kcal"


def test_fmt_ml_never_approx():
    """Água/volume nunca recebem ≈ (medida direta)."""
    assert mf._fmt_ml(1200) == "1.200 ml"


# ---------------------------------------------------------------------------
# log_food (SP-118)
# ---------------------------------------------------------------------------


def _food_item(
    kcal=100, protein=5, carbs=15, fat=1, fiber=2, is_estimate=False, needs_confirmation=False
):
    return SimpleNamespace(
        kcal=Decimal(str(kcal)),
        protein_g=Decimal(str(protein)),
        carbs_g=Decimal(str(carbs)),
        fat_g=Decimal(str(fat)),
        fiber_g=Decimal(str(fiber)),
        is_estimate=is_estimate,
        needs_confirmation=needs_confirmation,
        detected_name="arroz",
    )


def test_compose_meal_uses_meal_slot_pt_br():
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="lunch"),
        items=[_food_item()],
        warnings=[],
    )
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=_snap()), date(2026, 7, 20))
    assert "Registrei almoço." in out
    assert "Total da refeição — Almoço" in out


def test_compose_meal_breakfast_slot():
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="breakfast"),
        items=[_food_item()],
        warnings=[],
    )
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=_snap()), date(2026, 7, 20))
    assert "Total da refeição — Café da manhã" in out


def test_compose_meal_aggregates_only_current_items():
    """Tabela da refeição soma só os items da mensagem, não os totais do dia."""
    items = [
        _food_item(kcal=100, protein=5, carbs=15, fat=1, fiber=2),
        _food_item(kcal=200, protein=10, carbs=30, fat=3, fiber=4),
    ]
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="lunch"),
        items=items,
        warnings=[],
    )
    # Snapshot do dia inclui outras refeições
    snap = _snap(kcal_in=500, protein_g=30, carbs_g=60, fat_g=8, fiber_g=10)
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=snap), date(2026, 7, 20))
    # Refeição = 300 kcal, dia = 500
    assert "| Calorias | 300 kcal |" in out
    assert "| Calorias Consumidas | 500 kcal |" in out


def test_compose_meal_approx_when_item_is_estimate():
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="lunch"),
        items=[_food_item(is_estimate=True)],
        warnings=[],
    )
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=_snap(kcal_in=100)), date(2026, 7, 20))
    assert "≈ 100 kcal" in out


def test_compose_meal_no_approx_when_exact():
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="lunch"),
        items=[_food_item(is_estimate=False, needs_confirmation=False)],
        warnings=[],
    )
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=_snap(kcal_in=100)), date(2026, 7, 20))
    # Sem ≈ em nenhuma linha nutricional
    assert "≈" not in out


def _food_item_with_id(item_id: str, detected_name: str = "arroz"):
    it = _food_item()
    it.id = item_id
    it.detected_name = detected_name
    return it


def test_compose_meal_appends_recovery_block_when_no_catalog_hit():
    """SP-140: quando há warnings `no_catalog_hit`, o composer adiciona
    marcador HTML-comment com IDs + bloco com 3 CTAs em pt-BR."""
    item = _food_item_with_id("11111111-1111-1111-1111-111111111111", "pão de queijo")
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="breakfast"),
        items=[item],
        warnings=[
            {"code": "no_catalog_hit", "item_id": item.id, "detected_name": item.detected_name}
        ],
    )
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=_snap()), date(2026, 7, 20))

    # Marcador com IDs — usado pelo AssistantContent no frontend.
    assert "<!-- catalog-recovery: 11111111-1111-1111-1111-111111111111 -->" in out
    # Bloco em pt-BR com as 3 CTAs.
    assert "Sem catálogo para:" in out
    assert "**pão de queijo**" in out
    assert "Enviar foto do rótulo" in out
    assert "Cadastrar manualmente" in out
    assert "Descartar item" in out


def test_compose_meal_no_recovery_block_when_all_items_have_catalog():
    """Sem warnings `no_catalog_hit`, nada muda no output."""
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="lunch"),
        items=[_food_item()],
        warnings=[],
    )
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=_snap()), date(2026, 7, 20))
    assert "catalog-recovery" not in out
    assert "Sem catálogo para" not in out


def test_compose_meal_recovery_lists_only_no_catalog_items():
    """Mistura: só o item marcado como sem catálogo aparece no bloco."""
    with_catalog = _food_item_with_id("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "arroz")
    without = _food_item_with_id("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "tapioca")
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="lunch"),
        items=[with_catalog, without],
        warnings=[
            {
                "code": "no_catalog_hit",
                "item_id": without.id,
                "detected_name": without.detected_name,
            }
        ],
    )
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=_snap()), date(2026, 7, 20))
    assert "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" in out
    assert "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" not in out
    assert "**tapioca**" in out
    assert "**arroz**" not in out.split("Sem catálogo para:")[-1]


def test_compose_meal_daily_shows_kcal_out_only_when_positive():
    """Sem atividade registrada, Calorias Gastas / Saldo não aparecem."""
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="lunch"),
        items=[_food_item()],
        warnings=[],
    )
    snap = _snap(kcal_in=500, kcal_out=0, kcal_balance=500)
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=snap), date(2026, 7, 20))
    assert "Calorias Gastas" not in out
    assert "Saldo Calórico" not in out


def test_compose_meal_daily_shows_kcal_out_when_activity_done():
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="lunch"),
        items=[_food_item()],
        warnings=[],
    )
    snap = _snap(kcal_in=500, kcal_out=300, kcal_balance=200)
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=snap), date(2026, 7, 20))
    assert "| Calorias Gastas | 300 kcal |" in out
    assert "Saldo Calórico" in out


# ---------------------------------------------------------------------------
# log_water (SP-118)
# ---------------------------------------------------------------------------


def test_compose_water_ptbr_header_and_table():
    hydration = SimpleNamespace(record=SimpleNamespace(volume_ml=1200))
    snap = _snap(water_ml=1200)
    out = mf.compose_water(hydration, SimpleNamespace(snapshot=snap), date(2026, 7, 20))
    assert "Registrei 1.200 ml de água." in out
    assert "Total do registro" in out
    assert "| Água | 1.200 ml |" in out
    assert "| Água Pura | 1.200 ml |" in out
    assert "≈" not in out


# ---------------------------------------------------------------------------
# log_beverage (SP-118)
# ---------------------------------------------------------------------------


def test_compose_beverage_table_with_volume_row():
    beverage = SimpleNamespace(
        record=SimpleNamespace(
            detected_name="café expresso",
            volume_ml=50,
            kcal=Decimal(0),
            protein_g=Decimal(0),
            carbs_g=Decimal(0),
            fat_g=Decimal(0),
            fiber_g=Decimal(0),
            needs_confirmation=False,
        ),
        warnings=[],
    )
    snap = _snap(other_liquids_ml=50, water_ml=0)
    out = mf.compose_beverage(beverage, SimpleNamespace(snapshot=snap), date(2026, 7, 20))
    assert "Total da bebida — café expresso" in out
    assert "| Volume | 50 ml |" in out
    # Líquidos Totais com asterisco (other_ml > 0)
    assert "| Líquidos Totais* | 50 ml |" in out
    assert "inclui café, leite" in out


def test_compose_beverage_no_star_when_only_water():
    """Sem outros líquidos, o rótulo `Líquidos Totais` fica sem *."""
    beverage = SimpleNamespace(
        record=SimpleNamespace(
            detected_name="água com gás",
            volume_ml=250,
            kcal=Decimal(0),
            protein_g=Decimal(0),
            carbs_g=Decimal(0),
            fat_g=Decimal(0),
            fiber_g=Decimal(0),
            needs_confirmation=False,
        ),
        warnings=[],
    )
    snap = _snap(water_ml=500, other_liquids_ml=0)
    out = mf.compose_beverage(beverage, SimpleNamespace(snapshot=snap), date(2026, 7, 20))
    assert "| Líquidos Totais | 500 ml |" in out
    assert "| Líquidos Totais* |" not in out


# ---------------------------------------------------------------------------
# log_activity (SP-118)
# ---------------------------------------------------------------------------


def test_compose_activity_table_with_duration_and_kcal():
    activity = SimpleNamespace(
        record=SimpleNamespace(
            detected_name="corrida",
            duration_minutes=Decimal(40),
            intensity="moderate",
            kcal_burned=Decimal(359),
            calc_method="mets_body_weight",
            met_value=Decimal("8.3"),
        ),
    )
    snap = _snap(kcal_in=0, kcal_out=359, kcal_balance=-359)
    out = mf.compose_activity(activity, SimpleNamespace(snapshot=snap), date(2026, 7, 20))
    assert "Registrei 40 min de corrida (moderada)." in out
    assert "Total do exercício — corrida" in out
    assert "| Duração | 40 min |" in out
    assert "| Calorias gastas | 359 kcal |" in out
    # Saldo negativo formatado com sinal
    assert "-359 kcal" in out


def test_compose_activity_user_manual_shows_device_hint():
    activity = SimpleNamespace(
        record=SimpleNamespace(
            detected_name="corrida",
            duration_minutes=Decimal(30),
            intensity="vigorous",
            kcal_burned=Decimal(500),
            calc_method="user_manual",
            met_value=None,
        ),
    )
    snap = _snap(kcal_out=500)
    out = mf.compose_activity(activity, SimpleNamespace(snapshot=snap), date(2026, 7, 20))
    assert "(informado pelo dispositivo)" in out
    # user_manual não vira aproximação
    assert "≈ 500 kcal" not in out


# ---------------------------------------------------------------------------
# Data no cabeçalho
# ---------------------------------------------------------------------------


def test_daily_table_header_shows_local_date():
    meal = SimpleNamespace(
        food_record=SimpleNamespace(meal_slot="lunch"),
        items=[_food_item()],
        warnings=[],
    )
    out = mf.compose_meal(meal, SimpleNamespace(snapshot=_snap()), date(2026, 3, 15))
    assert "Total acumulado — 15/03/2026" in out
