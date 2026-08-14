/**
 * Tipos compartilhados entre fixtures (test.ts), seed e specs.
 * Evitam duplicação do shape da fila de LLM do TestAnthropicClient.
 */

export type LLMKind = 'record_intent' | 'record_intent_error' | 'narrative' | 'weekly_narrative';

export type QueuePayload =
  | { kind: 'record_intent'; envelope: Record<string, unknown> }
  | { kind: 'record_intent_error'; error: string }
  | { kind: 'narrative' | 'weekly_narrative'; text: string | null };

export type QueueLlmFn = (payload: QueuePayload) => Promise<void>;