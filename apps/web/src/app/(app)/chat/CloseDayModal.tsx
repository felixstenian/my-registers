'use client';

/**
 * T-704 / SP-100..SP-104 — Modal de encerramento do dia.
 *
 * Fluxo:
 * 1. Usuário clica "Encerrar dia" no DayTotalsBar.
 * 2. Modal pede confirmação (encerramento é imutável — INV-5).
 * 3. Ao confirmar, chama POST /days/{today}/close.
 * 4. Backend responde com totals finais + narrative da LLM. Renderizamos
 *    inline como resumo pós-fechamento; usuário pode fechar o modal ou
 *    ir para o relatório semanal.
 *
 * SP-101: idempotente. Se o dia já estava fechado, `was_already_closed=true`
 * e mostramos aviso amigável em vez de erro.
 */

import { useState } from 'react';
import { api } from '@/lib/api-client';

type Totals = {
  kcal_in: number;
  kcal_out: number;
  kcal_balance: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  water_ml: number;
  other_liquids_ml: number;
};

type CloseResponse = {
  date: string;
  status: 'closed';
  closed_at: string | null;
  totals: Totals;
  warnings: Array<{ code?: string; [key: string]: unknown }>;
  narrative: string | null;
  was_already_closed: boolean;
};

const nfInt = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
const nfDate = new Intl.DateTimeFormat('pt-BR', {
  weekday: 'long',
  day: '2-digit',
  month: 'long',
  year: 'numeric',
});

function fmtInt(n: number): string {
  return nfInt.format(n);
}

function fmtDatePt(iso: string): string {
  // ISO YYYY-MM-DD tratado como data local (sem timezone drift).
  const [y, m, d] = iso.split('-').map((s) => parseInt(s, 10));
  const dt = new Date(y, m - 1, d);
  return nfDate.format(dt);
}

export function CloseDayModal({
  date,
  onClose,
  onClosed,
}: {
  date: string; // YYYY-MM-DD
  onClose: () => void;
  onClosed: () => void;
}) {
  const [state, setState] = useState<
    | { phase: 'confirm' }
    | { phase: 'submitting' }
    | { phase: 'done'; data: CloseResponse }
    | { phase: 'error'; message: string }
  >({ phase: 'confirm' });

  const submit = async () => {
    setState({ phase: 'submitting' });
    const result = await api<CloseResponse>(`/days/${date}/close`, {
      method: 'POST',
    });
    if (result.ok) {
      setState({ phase: 'done', data: result.data });
      onClosed();
    } else {
      setState({
        phase: 'error',
        message: result.error?.message ?? 'Não foi possível encerrar o dia.',
      });
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl dark:bg-slate-900">
        {state.phase === 'confirm' && (
          <>
            <h2 className="text-lg font-semibold">Encerrar o dia?</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
              Depois de encerrado, o dia fica <strong>imutável</strong>: não é
              possível adicionar, corrigir ou remover registros.
            </p>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
              Data: <strong>{fmtDatePt(date)}</strong>
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={submit}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900"
              >
                Encerrar
              </button>
            </div>
          </>
        )}

        {state.phase === 'submitting' && (
          <div className="text-sm text-slate-600 dark:text-slate-400">
            Encerrando o dia… (gerando resumo)
          </div>
        )}

        {state.phase === 'error' && (
          <>
            <h2 className="text-lg font-semibold text-red-600 dark:text-red-400">
              Falha ao encerrar
            </h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
              {state.message}
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900"
              >
                Fechar
              </button>
            </div>
          </>
        )}

        {state.phase === 'done' && (
          <ClosedSummary data={state.data} onClose={onClose} />
        )}
      </div>
    </div>
  );
}

function ClosedSummary({ data, onClose }: { data: CloseResponse; onClose: () => void }) {
  const t = data.totals;
  const balance = t.kcal_balance;
  return (
    <>
      <h2 className="text-lg font-semibold">
        {data.was_already_closed ? 'Este dia já estava encerrado' : 'Dia encerrado'}
      </h2>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        {fmtDatePt(data.date)}
      </p>

      <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
        <SummaryRow label="Calorias in" value={`${fmtInt(t.kcal_in)} kcal`} />
        {t.kcal_out > 0 && (
          <SummaryRow label="Calorias out" value={`${fmtInt(t.kcal_out)} kcal`} />
        )}
        {t.kcal_out > 0 && (
          <SummaryRow
            label="Saldo"
            value={`${balance >= 0 ? '+' : ''}${fmtInt(balance)} kcal`}
          />
        )}
        <SummaryRow label="Proteína" value={`${fmtInt(t.protein_g)} g`} />
        <SummaryRow label="Carboidrato" value={`${fmtInt(t.carbs_g)} g`} />
        <SummaryRow label="Gordura" value={`${fmtInt(t.fat_g)} g`} />
        <SummaryRow label="Fibra" value={`${fmtInt(t.fiber_g)} g`} />
        <SummaryRow label="Água" value={`${fmtInt(t.water_ml)} ml`} />
        {t.other_liquids_ml > 0 && (
          <SummaryRow label="Outros líq." value={`${fmtInt(t.other_liquids_ml)} ml`} />
        )}
      </div>

      {data.narrative && (
        <div className="mt-4 rounded border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-800/40">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Resumo
          </div>
          <p className="whitespace-pre-wrap text-slate-700 dark:text-slate-200">
            {data.narrative}
          </p>
        </div>
      )}

      {data.warnings.length > 0 && (
        <div className="mt-3 text-xs text-amber-700 dark:text-amber-300">
          {data.warnings.length}{' '}
          {data.warnings.length === 1 ? 'aviso registrado' : 'avisos registrados'}
        </div>
      )}

      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <a
          href="/weekly"
          className="rounded px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          Ver semana
        </a>
        <button
          type="button"
          onClick={onClose}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900"
        >
          Voltar
        </button>
      </div>
    </>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-slate-100 pb-1 dark:border-slate-800">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
