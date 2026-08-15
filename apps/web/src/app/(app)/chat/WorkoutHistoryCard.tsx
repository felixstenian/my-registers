'use client';

/**
 * T-B308 (SP-127) — card dedicado para `llm_intent='workout_history'`.
 *
 * Embrulha o markdown do backend (`message_formatter.compose_workout_history`)
 * num container com identidade visual de histórico de treino. O parser de
 * blocos/tabelas e o destaque do PR continuam no `AssistantContent`.
 */

import { AssistantContent } from './AssistantContent';

export function WorkoutHistoryCard({ content }: { content: string }) {
  return (
    <div className="overflow-hidden rounded-lg border border-emerald-300 bg-emerald-50/40 dark:border-emerald-800 dark:bg-emerald-950/20">
      <p className="border-b border-emerald-300 bg-emerald-100/60 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-emerald-800 dark:border-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200">
        🏋️ Histórico de treino
      </p>
      <div className="p-3">
        <AssistantContent content={content} intent="workout_history" />
      </div>
    </div>
  );
}