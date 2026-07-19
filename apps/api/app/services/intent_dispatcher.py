"""IntentDispatcher — roteia LLMEnvelope validado para os services de negócio.

Fase 3 conecta apenas `clarify` e `unknown` (retornam `content` para o
assistant); qualquer intent estruturado (`log_food`, `log_water`, …) levanta
`IntentNotImplemented`, capturado pelo `MessageProcessor` e virado em pedido
de esclarecimento para o usuário. Fases 4-8 vão substituir esses stubs
pelos services reais (SP-20+).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.llm import LLMEnvelope

# Fallbacks são mensagens DIRIGIDAS AO USUÁRIO (2ª pessoa). Nunca cair no
# `user_text_summary` como conteúdo do assistant — esse campo é resumo em 3ª
# pessoa para log/auditoria interna, não fala com o usuário.
_FALLBACK_UNKNOWN = (
    "Consegui receber sua mensagem, mas não deu para saber o que você "
    "quer registrar. Pode reformular?"
)
_FALLBACK_CLARIFY = (
    "Pode me contar mais? Você comeu algo, bebeu, treinou, "
    "ou é só um comentário sobre o dia?"
)

# Intents que o MessageProcessor trata diretamente (persistência custom):
# - log_food (Fase 4), log_water/log_beverage/log_activity (Fase 5).
# Não devem passar pelo dispatcher; se chegarem aqui é bug e cai como unknown.
# Intents que ainda dependem de fase futura ficam aqui:
_STRUCTURED_INTENTS = {
    "log_nutrition_label",  # Fase 4.b
    "query_day",  # Fase 7
    "close_day",  # Fase 7
    "weekly_summary",  # Fase 8
}


class IntentNotImplemented(Exception):
    def __init__(self, intent: str) -> None:
        super().__init__(intent)
        self.intent = intent


@dataclass(slots=True)
class DispatchResult:
    content: str
    llm_intent: str
    llm_confidence: float


class IntentDispatcher:
    """Fase 3: entrega apenas `clarify`/`unknown`. Demais → NotImplemented."""

    def dispatch(self, envelope: LLMEnvelope) -> DispatchResult:
        if envelope.intent == "clarify":
            # Só usamos o campo user-facing (2ª pessoa). Se a LLM esqueceu de
            # preencher `clarification_question`, entregamos o fallback padrão
            # em vez de vazar o `user_text_summary` (que é 3ª pessoa e soa
            # estranho para o usuário — SP-13 UX).
            content = envelope.clarification_question or _FALLBACK_CLARIFY
            return DispatchResult(
                content=content,
                llm_intent=envelope.intent,
                llm_confidence=envelope.confidence,
            )
        if envelope.intent == "unknown":
            return DispatchResult(
                content=_FALLBACK_UNKNOWN,
                llm_intent=envelope.intent,
                llm_confidence=envelope.confidence,
            )
        if envelope.intent in _STRUCTURED_INTENTS:
            raise IntentNotImplemented(envelope.intent)
        # intent válido do schema mas fora dos conjuntos conhecidos: trata como unknown
        return DispatchResult(
            content=_FALLBACK_UNKNOWN,
            llm_intent="unknown",
            llm_confidence=envelope.confidence,
        )
