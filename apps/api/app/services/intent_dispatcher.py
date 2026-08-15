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
    "Pode me contar mais? Você comeu algo, bebeu, treinou, ou é só um comentário sobre o dia?"
)

# Nenhum intent estruturado permanece pendente após a Fase 4.b — todos são
# roteados diretamente pelo `MessageProcessor`. Mantemos o set vazio como
# extension point caso apareça algo novo no futuro.
_STRUCTURED_INTENTS: set[str] = set()

# SP-120..SP-127 (Bloco 3) + SP-171 (Bloco 3.b): intents de treino são
# roteados DIRETAMENTE pelo `MessageProcessor` (handlers `_handle_workout_*`),
# sem passar por `_STRUCTURED_INTENTS` nem cair no fallback `unknown` aqui.
# `workout_correct` (SP-175) entra no T-B322 junto com seu handler.
WORKOUT_INTENTS: frozenset[str] = frozenset(
    {
        "workout_start",
        "workout_add_exercise",
        "workout_log_set",
        "workout_end",
        "workout_history",
        # SP-171 (Bloco 3.b): cadastro de treino reutilizável por texto.
        "workout_register_template",
        # SP-178 (T-B319): botão "Ir para o próximo exercício" (fluxo guiado).
        "workout_next_exercise",
    }
)


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

    def is_workout_intent(self, intent: str) -> bool:
        """SP-120..SP-127: intents de treino roteados pelo MessageProcessor."""
        return intent in WORKOUT_INTENTS

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
