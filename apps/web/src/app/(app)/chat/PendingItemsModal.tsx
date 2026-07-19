'use client';

/**
 * SP-117 — modal de confirmação inline de itens pendentes.
 *
 * Chamado a partir do badge do `DayTotalsBar` quando existem
 * `food_items` com `needs_confirmation=true`. Para cada item:
 *
 * - **Confirmar** — re-envia a mesma grama (ou ml) via
 *   `PATCH /records/food-items/{id}`. O backend recomputa macros pelo
 *   catálogo E marca `needs_confirmation=false` na mesma transação. (Ver
 *   `records.patch_food_item` no backend.)
 * - **Descartar** — `DELETE /records/food-items/{id}` (soft delete + recompute).
 *
 * Após qualquer ação bem-sucedida, o modal sinaliza `onChanged()` para o
 * pai revalidar `/days/today` e a mensagem sumir da lista.
 */

import { useState } from 'react';
import { api } from '@/lib/api-client';
import type { FoodItemRef } from './DayTotalsBar';

const nfInt = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });

function amountLabel(item: FoodItemRef): string {
  if (item.grams && item.grams > 0) return `${nfInt.format(item.grams)}g`;
  if (item.ml && item.ml > 0) return `${nfInt.format(item.ml)}ml`;
  if (item.quantity && item.unit) return `${item.quantity} ${item.unit}`;
  return '?';
}

export function PendingItemsModal({
  items,
  onClose,
  onChanged,
}: {
  items: FoodItemRef[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);

  async function confirm(item: FoodItemRef) {
    setBusyId(item.id);
    // SP-117: confirmar = re-enviar o valor atual, o backend recomputa
    // catálogo e limpa `needs_confirmation`.
    const patch: Record<string, number> = {};
    if (item.grams && item.grams > 0) patch.grams = item.grams;
    else if (item.ml && item.ml > 0) patch.ml = item.ml;
    else if (item.quantity && item.quantity > 0) patch.quantity = item.quantity;
    const result = await api(`/records/food-items/${item.id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
    setBusyId(null);
    if (result.ok) onChanged();
  }

  async function discard(item: FoodItemRef) {
    setBusyId(item.id);
    const result = await api(`/records/food-items/${item.id}`, { method: 'DELETE' });
    setBusyId(null);
    if (result.ok) onChanged();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Itens pendentes de confirmação"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-4 shadow-xl dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Itens pendentes de confirmação</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="text-slate-500 hover:text-slate-800 dark:hover:text-slate-100"
          >
            ×
          </button>
        </div>

        {items.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Nenhum item pendente. Você pode fechar.
          </p>
        ) : (
          <ul className="space-y-2">
            {items.map((item) => (
              <li
                key={item.id}
                className="flex items-center gap-3 rounded border border-amber-300 bg-amber-50 p-2 text-xs dark:border-amber-800 dark:bg-amber-900/30"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{item.detected_name}</div>
                  <div className="text-slate-600 dark:text-slate-400">
                    {amountLabel(item)}
                    {typeof item.kcal === 'number' && (
                      <> · {nfInt.format(item.kcal)} kcal</>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  disabled={busyId === item.id}
                  onClick={() => confirm(item)}
                  className="rounded bg-emerald-600 px-2.5 py-1 text-white transition hover:bg-emerald-700 disabled:opacity-60"
                >
                  Confirmar
                </button>
                <button
                  type="button"
                  disabled={busyId === item.id}
                  onClick={() => discard(item)}
                  className="rounded border border-slate-300 px-2.5 py-1 text-slate-700 transition hover:bg-slate-100 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                >
                  Descartar
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
