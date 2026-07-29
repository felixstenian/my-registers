'use client';

/**
 * SP-141 / SP-142 — formulário de cadastro manual de nutrient_facts.
 *
 * Aberto pelo CTA "Cadastrar manualmente" do bloco recovery (SP-140)
 * no `AssistantContent`. Envia `POST /nutrient-facts/manual`; se
 * `promoteFoodItemId` está setado, backend também promove o item
 * (SP-142) e recomputa o snapshot.
 *
 * Escopo v1: campos mínimos obrigatórios (nome canonical, basis, kcal,
 * P/C/G). Fibra e micros ficam em accordion. Sem edição de fact
 * existente aqui — só criação nova.
 */

import { api } from '@/lib/api-client';
import { FormEvent, useState } from 'react';

type Props = {
  // Um item sem catálogo — se presente, o cadastro promove o item.
  promoteFoodItemId?: string;
  // Nome detectado (usado como sugestão de canonical_name).
  suggestedName?: string;
  onClose: () => void;
  onSuccess: () => void;
};

// Normaliza pro formato aceito pelo backend: [a-z0-9_]+
function toCanonical(name: string): string {
  return name
    .toLowerCase()
    .normalize('NFD')
    // eslint-disable-next-line no-misleading-character-class
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

export function ManualCatalogForm({
  promoteFoodItemId,
  suggestedName,
  onClose,
  onSuccess,
}: Props) {
  const [canonicalName, setCanonicalName] = useState(
    suggestedName ? toCanonical(suggestedName) : '',
  );
  const [displayName, setDisplayName] = useState(suggestedName ?? '');
  const [brand, setBrand] = useState('');
  const [basis, setBasis] = useState<'per_100g' | 'per_100ml'>('per_100g');
  const [kcal, setKcal] = useState('');
  const [protein, setProtein] = useState('');
  const [carbs, setCarbs] = useState('');
  const [fat, setFat] = useState('');
  const [fiber, setFiber] = useState('');
  const [sodium, setSodium] = useState('');
  const [showMicros, setShowMicros] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const canSubmit =
    canonicalName.trim().length >= 2 &&
    kcal !== '' &&
    protein !== '' &&
    carbs !== '' &&
    fat !== '' &&
    !submitting;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setSuccess(null);

    const payload: Record<string, unknown> = {
      canonical_name: canonicalName.trim(),
      display_name: displayName.trim() || undefined,
      brand: brand.trim() || undefined,
      basis,
      kcal: Number(kcal),
      protein_g: Number(protein),
      carbs_g: Number(carbs),
      fat_g: Number(fat),
    };
    if (fiber !== '') payload.fiber_g = Number(fiber);
    if (sodium !== '') payload.sodium_mg = Number(sodium);
    if (promoteFoodItemId) payload.promote_food_item_id = promoteFoodItemId;

    const result = await api<{ promotion_warning: string | null; promoted_item_id: string | null }>(
      '/nutrient-facts/manual',
      { method: 'POST', body: JSON.stringify(payload) },
    );
    setSubmitting(false);

    if (!result.ok) {
      setError(result.error?.message ?? 'Falha ao cadastrar. Verifique os valores.');
      return;
    }

    if (result.data.promotion_warning) {
      setSuccess(
        `Fact cadastrado, mas a promoção falhou (${result.data.promotion_warning}). ` +
          'Você pode corrigir o item pelo chat: "corrija <nome> <grams>g".',
      );
    } else {
      setSuccess('Cadastrado com sucesso! Fechando…');
      setTimeout(() => {
        onSuccess();
      }, 600);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Cadastrar item no catálogo"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-5 shadow-xl dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Cadastrar item no catálogo</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="text-slate-500 hover:text-slate-800 dark:hover:text-slate-100"
          >
            ×
          </button>
        </div>

        <form onSubmit={onSubmit} className="space-y-3 text-sm">
          <Field label="Nome de exibição (opcional)" hint="Ex.: Pão de queijo congelado">
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="input"
            />
          </Field>

          <Field
            label="ID canonical"
            hint="Só letras minúsculas, dígitos e _. Usado internamente para lookup."
          >
            <input
              type="text"
              value={canonicalName}
              onChange={(e) => setCanonicalName(e.target.value)}
              required
              pattern="[a-z0-9_]{2,}"
              className="input font-mono"
            />
          </Field>

          <Field label="Marca (opcional)">
            <input
              type="text"
              value={brand}
              onChange={(e) => setBrand(e.target.value)}
              className="input"
            />
          </Field>

          <Field label="Base">
            <select
              value={basis}
              onChange={(e) => setBasis(e.target.value as 'per_100g' | 'per_100ml')}
              className="input"
            >
              <option value="per_100g">Por 100 g (sólido)</option>
              <option value="per_100ml">Por 100 ml (líquido)</option>
            </select>
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label={`Calorias por 100 ${basis === 'per_100g' ? 'g' : 'ml'}`}>
              <input
                type="number"
                min={0}
                max={10000}
                step="0.1"
                value={kcal}
                onChange={(e) => setKcal(e.target.value)}
                required
                className="input"
              />
            </Field>
            <Field label="Proteína (g)">
              <input
                type="number"
                min={0}
                max={1000}
                step="0.1"
                value={protein}
                onChange={(e) => setProtein(e.target.value)}
                required
                className="input"
              />
            </Field>
            <Field label="Carboidrato (g)">
              <input
                type="number"
                min={0}
                max={1000}
                step="0.1"
                value={carbs}
                onChange={(e) => setCarbs(e.target.value)}
                required
                className="input"
              />
            </Field>
            <Field label="Gordura (g)">
              <input
                type="number"
                min={0}
                max={1000}
                step="0.1"
                value={fat}
                onChange={(e) => setFat(e.target.value)}
                required
                className="input"
              />
            </Field>
          </div>

          <details open={showMicros} onToggle={(e) => setShowMicros(e.currentTarget.open)}>
            <summary className="cursor-pointer select-none text-xs text-slate-500 dark:text-slate-400">
              Micros e fibras (opcional)
            </summary>
            <div className="mt-2 grid grid-cols-2 gap-3">
              <Field label="Fibra (g)">
                <input
                  type="number"
                  min={0}
                  step="0.1"
                  value={fiber}
                  onChange={(e) => setFiber(e.target.value)}
                  className="input"
                />
              </Field>
              <Field label="Sódio (mg)">
                <input
                  type="number"
                  min={0}
                  step="1"
                  value={sodium}
                  onChange={(e) => setSodium(e.target.value)}
                  className="input"
                />
              </Field>
            </div>
          </details>

          {promoteFoodItemId && (
            <p className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">
              O item pendente será atualizado automaticamente com estes valores.
            </p>
          )}

          {error && (
            <p role="alert" className="text-xs text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
          {success && (
            <p role="status" className="text-xs text-emerald-700 dark:text-emerald-300">
              {success}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white transition disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
            >
              {submitting ? 'Cadastrando…' : 'Cadastrar'}
            </button>
          </div>
        </form>
      </div>

      <style jsx>{`
        :global(.input) {
          display: block;
          width: 100%;
          border-radius: 4px;
          border: 1px solid rgb(203 213 225);
          background-color: white;
          padding: 4px 8px;
          font-size: 0.8125rem;
          color: rgb(15 23 42);
        }
        :global(.dark .input) {
          border-color: rgb(51 65 85);
          background-color: rgb(15 23 42);
          color: rgb(226 232 240);
        }
      `}</style>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">
        {label}
      </span>
      {children}
      {hint && (
        <span className="mt-0.5 block text-[10px] text-slate-500 dark:text-slate-400">{hint}</span>
      )}
    </label>
  );
}
