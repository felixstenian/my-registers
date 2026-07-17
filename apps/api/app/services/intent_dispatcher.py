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

_FALLBACK_UNKNOWN = (
    "Consegui receber sua mensagem, mas não deu para saber o que você "
    "quer registrar. Pode reformular?"
)
_FALLBACK_CLARIFY = "Pode me dar mais detalhes?"

_STRUCTURED_INTENTS = {
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
            content = (
                envelope.clarification_question
                or envelope.user_text_summary
                or _FALLBACK_CLARIFY
            )
            return DispatchResult(
                content=content,
                llm_intent=envelope.intent,
                llm_confidence=envelope.confidence,
            )
        if envelope.intent == "unknown":
            content = envelope.user_text_summary or _FALLBACK_UNKNOWN
            return DispatchResult(
                content=content,
                llm_intent=envelope.intent,
                llm_confidence=envelope.confidence,
            )
        if envelope.intent in _STRUCTURED_INTENTS:
            raise IntentNotImplemented(envelope.intent)
        # intent válido do schema mas fora dos conjuntos conhecidos: trata como unknown
        return DispatchResult(
            content=envelope.user_text_summary or _FALLBACK_UNKNOWN,
            llm_intent="unknown",
            llm_confidence=envelope.confidence,
        )
