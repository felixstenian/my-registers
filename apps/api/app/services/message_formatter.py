"""SP-118 — formato tabular padronizado das assistant messages.

Cada função de compose devolve **duas tabelas markdown** + disclaimer +
bloco opcional de warnings, seguindo a especificação:

1. Cabeçalho curto ("Registrei o almoço.").
2. Tabela "Total da refeição/registro" com título contextual.
3. Tabela "Total acumulado — DD/MM/YYYY".
4. Aviso legal (Const. §26).
5. Bloco de warnings de itens pendentes (opcional).

Regras de formatação:
- Números em pt-BR (vírgula decimal, ponto milhar): 1.200 ml, 46,7 g.
- `≈` (aproximadamente) aparece em linhas nutricionais **apenas** quando ao
  menos um item envolvido tem `is_estimate=true` ou `needs_confirmation=true`.
- Água pura e volume **nunca** recebem `≈` (medidas diretas).
- `Líquidos Totais` recebe `*` quando `other_liquids_ml > 0`, com nota
  abaixo da tabela.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

_DISCLAIMER = (
    "As estimativas nutricionais são aproximações e não substituem "
    "acompanhamento médico ou nutricional."
)

_MEAL_SLOT_LABELS: dict[str, str] = {
    "breakfast": "Café da manhã",
    "lunch": "Almoço",
    "snack": "Lanche",
    "dinner": "Jantar",
    "other": "Refeição",
    "unspecified": "Refeição",
}


# ---------------------------------------------------------------------------
# pt-BR number formatting
# ---------------------------------------------------------------------------


def _fmt_int(value) -> str:
    """`1200` → `1.200`."""
    if value is None:
        return "0"
    n = int(value)
    return f"{n:,}".replace(",", ".")


def _fmt_dec(value, digits: int = 1) -> str:
    """`46.7` → `46,7`. Zero decimais quando `digits=0`."""
    if value is None:
        return "0"
    q = Decimal(str(value)).quantize(Decimal("0.1") ** digits)
    s = f"{q:,.{digits}f}"
    # Troca separadores: en → pt-BR (,/. invertidos).
    s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return s


def _fmt_kcal(value, approx: bool) -> str:
    prefix = "≈ " if approx else ""
    return f"{prefix}{_fmt_int(value)} kcal"


def _fmt_g(value, approx: bool, digits: int = 1) -> str:
    prefix = "≈ " if approx else ""
    return f"{prefix}{_fmt_dec(value, digits)} g"


def _fmt_ml(value) -> str:
    """Água/volumes — sempre exato, nunca `≈`."""
    return f"{_fmt_int(value)} ml"


def _fmt_min(value) -> str:
    return f"{_fmt_int(value)} min"


# ---------------------------------------------------------------------------
# Table primitives
# ---------------------------------------------------------------------------


def _table(title: str, rows: list[tuple[str, str]]) -> str:
    """Markdown 2-column table: `Indicador | Total`."""
    lines = [
        f"**{title}**",
        "",
        "| Indicador | Total |",
        "| --- | --- |",
    ]
    for label, value in rows:
        lines.append(f"| {label} | {value} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Snapshot → tabela de totais diários (comum a todos os intents)
# ---------------------------------------------------------------------------


def _daily_totals_table(snapshot, log_date: date, approx: bool) -> str:
    title = f"Total acumulado — {log_date.strftime('%d/%m/%Y')}"
    rows: list[tuple[str, str]] = [
        ("Calorias Consumidas", _fmt_kcal(snapshot.kcal_in, approx)),
    ]
    kcal_out = int(snapshot.kcal_out or 0)
    if kcal_out > 0:
        rows.append(("Calorias Gastas", _fmt_kcal(snapshot.kcal_out, approx)))
        # Saldo mostra sinal explícito (kcal_balance = kcal_in - kcal_out).
        balance = int(snapshot.kcal_balance or 0)
        sign = "+" if balance >= 0 else ""
        approx_prefix = "≈ " if approx else ""
        rows.append(
            (
                "Saldo Calórico",
                f"{approx_prefix}{sign}{_fmt_int(balance)} kcal",
            )
        )
    rows.extend(
        [
            ("Proteínas", _fmt_g(snapshot.protein_g, approx)),
            ("Carboidratos", _fmt_g(snapshot.carbs_g, approx)),
            ("Gorduras", _fmt_g(snapshot.fat_g, approx)),
            ("Fibras", _fmt_g(snapshot.fiber_g, approx)),
            ("Água Pura", _fmt_ml(snapshot.water_ml)),
        ]
    )
    water_ml = int(snapshot.water_ml or 0)
    other_ml = int(snapshot.other_liquids_ml or 0)
    total_liquids = water_ml + other_ml
    has_other = other_ml > 0
    label = "Líquidos Totais*" if has_other else "Líquidos Totais"
    rows.append((label, _fmt_ml(total_liquids)))
    body = _table(title, rows)
    if has_other:
        body += "\n\n\\* inclui café, leite, sucos e outras bebidas calóricas."
    return body


# ---------------------------------------------------------------------------
# Approximation heuristic (used by kcal/g prefix `≈`)
# ---------------------------------------------------------------------------


def _has_approx_food_items(items, warnings: list[dict]) -> bool:
    if any(
        getattr(i, "is_estimate", False) or getattr(i, "needs_confirmation", False) for i in items
    ):
        return True
    codes = {w.get("code") for w in warnings}
    return bool({"low_confidence_item", "no_catalog_hit"} & codes)


# ---------------------------------------------------------------------------
# Composers per intent
# ---------------------------------------------------------------------------


def compose_meal(meal, recompute, log_date: date) -> str:
    """SP-118 para `log_food`.

    A tabela "Total da refeição" agrega apenas os `food_items` recém-criados
    nesta mensagem (não os totais acumulados do dia — esses vão para a 2ª
    tabela).
    """
    slot = meal.food_record.meal_slot or "unspecified"
    slot_label = _MEAL_SLOT_LABELS.get(slot, "Refeição")

    approx = _has_approx_food_items(meal.items, meal.warnings)

    # Agrega os itens desta mensagem (não do dia).
    kcal_sum = sum((_dec(i.kcal) for i in meal.items), Decimal(0))
    p_sum = sum((_dec(i.protein_g) for i in meal.items), Decimal(0))
    c_sum = sum((_dec(i.carbs_g) for i in meal.items), Decimal(0))
    f_sum = sum((_dec(i.fat_g) for i in meal.items), Decimal(0))
    fi_sum = sum((_dec(i.fiber_g) for i in meal.items), Decimal(0))

    meal_rows = [
        ("Calorias", _fmt_kcal(kcal_sum, approx)),
        ("Proteínas", _fmt_g(p_sum, approx)),
        ("Carboidratos", _fmt_g(c_sum, approx)),
        ("Gorduras", _fmt_g(f_sum, approx)),
        ("Fibras", _fmt_g(fi_sum, approx)),
    ]
    meal_table = _table(f"Total da refeição — {slot_label}", meal_rows)
    daily = _daily_totals_table(recompute.snapshot, log_date, approx)

    parts = [
        f"Registrei {slot_label.lower()}.",
        "",
        meal_table,
        "",
        daily,
        "",
        _DISCLAIMER,
    ]
    # SP-140: card de recuperação quando algum item ficou sem catálogo.
    recovery_block = _no_catalog_recovery_block(meal.items, meal.warnings)
    if recovery_block:
        parts.append("")
        parts.append(recovery_block)
    return "\n".join(parts)


# SP-140 — Marcador processado pelo AssistantContent do frontend pra
# transformar a linha em CTAs clicáveis (foto, cadastrar, descartar).
# Formato: `<!-- catalog-recovery: id1,id2 -->` seguido de listagem
# markdown legível. Se o frontend não reconhecer, a listagem markdown
# continua útil como texto puro.
_RECOVERY_MARKER = "<!-- catalog-recovery:"


def _no_catalog_recovery_block(items, warnings: list[dict]) -> str:
    """Retorna bloco pt-BR com CTAs quando 1+ item tem `no_catalog_hit`.

    Bloco inclui:
    - marcador HTML-comment com IDs dos items afetados (parseado pelo
      frontend em AssistantContent — invisível na renderização plain).
    - texto amigável com 3 caminhos: foto do rótulo, cadastro manual,
      descartar.
    """
    affected_ids = {
        w["item_id"] for w in warnings if w.get("code") == "no_catalog_hit" and w.get("item_id")
    }
    if not affected_ids:
        return ""
    # Mantém a ordem original dos items (LLM devolve nesta ordem).
    id_to_name = {str(it.id): it.detected_name for it in items}
    affected = [(str(it.id), it.detected_name) for it in items if str(it.id) in affected_ids]
    if not affected:
        return ""

    id_list = ",".join(id_ for id_, _ in affected)
    names = ", ".join(f"**{name}**" for _, name in affected)
    lines = [
        f"{_RECOVERY_MARKER} {id_list} -->",
        f"**Sem catálogo para:** {names}",
        "",
        "Como você quer resolver?",
        "- 📸 **Enviar foto do rótulo** — anexe no próximo message.",
        "- ✏️ **Cadastrar manualmente** — informe kcal e macros por 100 g/ml.",
        "- ❌ **Descartar item** — responda `apaga {nome}`.",
    ]
    # `id_to_name` intencionalmente não vira mais nada — mantém escopo
    # simples; frontend renderiza CTAs por item.
    _ = id_to_name
    return "\n".join(lines)


def compose_water(hydration, recompute, log_date: date) -> str:
    volume_ml = hydration.record.volume_ml
    water_table = _table(
        "Total do registro",
        [("Água", _fmt_ml(volume_ml))],
    )
    # Água pura NUNCA marca approx (é medida direta).
    daily = _daily_totals_table(recompute.snapshot, log_date, approx=False)
    parts = [
        f"Registrei {_fmt_int(volume_ml)} ml de água.",
        "",
        water_table,
        "",
        daily,
        "",
        _DISCLAIMER,
    ]
    return "\n".join(parts)


def compose_beverage(beverage, recompute, log_date: date) -> str:
    r = beverage.record
    detected = r.detected_name or "bebida"
    approx = bool(r.needs_confirmation) or any(
        w.get("code") in ("low_confidence_item", "no_catalog_hit") for w in beverage.warnings
    )

    bev_rows = [
        ("Calorias", _fmt_kcal(r.kcal or 0, approx)),
        ("Proteínas", _fmt_g(r.protein_g or 0, approx)),
        ("Carboidratos", _fmt_g(r.carbs_g or 0, approx)),
        ("Gorduras", _fmt_g(r.fat_g or 0, approx)),
        ("Fibras", _fmt_g(r.fiber_g or 0, approx)),
        ("Volume", _fmt_ml(r.volume_ml)),
    ]
    bev_table = _table(f"Total da bebida — {detected}", bev_rows)
    daily = _daily_totals_table(recompute.snapshot, log_date, approx=approx)
    parts = [
        f"Registrei {_fmt_int(r.volume_ml)} ml de {detected}.",
        "",
        bev_table,
        "",
        daily,
        "",
        _DISCLAIMER,
    ]
    return "\n".join(parts)


def compose_activity(activity, recompute, log_date: date) -> str:
    r = activity.record
    detected = r.detected_name or "exercício"
    duration = _fmt_min(r.duration_minutes)
    kcal_out = int(r.kcal_burned or 0)
    intensity_label = {
        "light": "leve",
        "moderate": "moderada",
        "vigorous": "intensa",
        "unknown": "sem intensidade informada",
    }.get(r.intensity, r.intensity)
    source_hint = " (informado pelo dispositivo)" if r.calc_method == "user_manual" else ""

    # Atividade não tem "estimativa" no sentido nutricional; o `≈` só entra
    # quando `calc_method != 'user_manual'` E met_value None (cálculo com fallback).
    approx = r.calc_method != "user_manual" and r.met_value is None

    act_rows = [
        ("Duração", duration),
        ("Calorias gastas", _fmt_kcal(kcal_out, approx)),
    ]
    act_table = _table(f"Total do exercício — {detected}", act_rows)
    # A tabela diária considera `approx` só se houver comida/bebida estimada
    # ou activity com calc_method estimado.
    daily = _daily_totals_table(recompute.snapshot, log_date, approx=approx)
    parts = [
        f"Registrei {duration} de {detected} ({intensity_label}){source_hint}.",
        "",
        act_table,
        "",
        daily,
        "",
        _DISCLAIMER,
    ]
    return "\n".join(parts)


def _dec(value) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
