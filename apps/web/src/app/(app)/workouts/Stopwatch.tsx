'use client';

/**
 * T-B320 (SP-179, RF-021) — cronômetro do treino.
 *
 * Decisão 8 (`trade-offs.md`): UI-only. O tempo exibido é derivado de
 * `started_at` da sessão ativa (`GET /workouts/session/active`, T-B317) e
 * atualizado a cada segundo só para feedback visual — a fonte determinística
 * do tempo registrado é sempre `ended_at - started_at` calculado no backend
 * (`WorkoutService.consolidate_to_activity`, SP-126). O componente não grava
 * nada; ele simplesmente para de existir quando a sessão ativa some (o pai
 * deixa de renderizá-lo ao `workout_end`).
 */

import { useEffect, useState } from 'react';

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0 ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

export function Stopwatch({ startedAt }: { startedAt: string }) {
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const startedMs = new Date(startedAt).getTime();
  const elapsedMs = Number.isNaN(startedMs) ? 0 : now - startedMs;

  return (
    <span
      role="timer"
      aria-live="off"
      className="inline-flex items-center gap-1 rounded bg-emerald-100 px-2 py-1 font-mono text-xs font-semibold text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200"
    >
      ⏱ {formatElapsed(elapsedMs)}
    </span>
  );
}
