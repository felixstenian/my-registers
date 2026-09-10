'use client';

// SP-185 — criação estruturada de registros (sem LLM) para /day/[date],
// restrita a dias em aberto (INV-25). Valores entram estruturados e o
// backend resolve o day_log por data, calcula e reaudita.

import { api } from '@/lib/api-client';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

type AddKind = 'food' | 'water' | 'beverage' | 'activity';

const MEAL_SLOTS = [
  { value: 'breakfast', label: 'Café da manhã' },
  { value: 'lunch', label: 'Almoço' },
  { value: 'snack', label: 'Lanche' },
  { value: 'dinner', label: 'Jantar' },
  { value: 'other', label: 'Outra refeição' },
  { value: 'unspecified', label: 'Sem refeição' },
];

const ACTIVITY_TYPES = [
  { value: 'cardio_walk', label: 'Caminhada' },
  { value: 'cardio_run', label: 'Corrida' },
  { value: 'cardio_bike', label: 'Ciclismo' },
  { value: 'cardio_swim', label: 'Natação' },
  { value: 'strength', label: 'Musculação' },
  { value: 'hiit', label: 'HIIT' },
  { value: 'yoga', label: 'Yoga' },
  { value: 'pilates', label: 'Pilates' },
  { value: 'other', label: 'Outra' },
];

export function DailyAddForm({ date }: { date: string }) {
  const router = useRouter();
  const [kind, setKind] = useState<AddKind>('food');
  const [name, setName] = useState('');
  const [amount, setAmount] = useState('');
  const [mealSlot, setMealSlot] = useState('unspecified');
  const [activityType, setActivityType] = useState('cardio_walk');
  const [duration, setDuration] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setName('');
    setAmount('');
    setDuration('');
    setError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);

    let path: string;
    let body: Record<string, unknown>;

    if (kind === 'water') {
      const v = parseInt(amount, 10);
      if (!v || v <= 0) {
        setError('Informe o volume em ml.');
        setSaving(false);
        return;
      }
      path = '/records/water';
      body = { log_date: date, volume_ml: v };
    } else if (kind === 'beverage') {
      const v = parseInt(amount, 10);
      if (!name.trim() || !v) {
        setError('Informe nome e volume.');
        setSaving(false);
        return;
      }
      path = '/records/beverage';
      body = { log_date: date, detected_name: name.trim(), volume_ml: v };
    } else if (kind === 'activity') {
      const d = parseFloat(duration);
      if (!name.trim() || !d || d <= 0) {
        setError('Informe nome e duração.');
        setSaving(false);
        return;
      }
      path = '/records/activity';
      body = {
        log_date: date,
        detected_name: name.trim(),
        activity_type: activityType,
        duration_minutes: d,
      };
    } else {
      const g = parseFloat(amount);
      if (!name.trim() || !g || g <= 0) {
        setError('Informe nome e quantidade (gramas).');
        setSaving(false);
        return;
      }
      path = '/records/food';
      body = {
        log_date: date,
        meal_slot: mealSlot,
        items: [{ detected_name: name.trim(), grams: g }],
      };
    }

    try {
      const res = await api(path, { method: 'POST', body: JSON.stringify(body) });
      if (!res.ok) {
        setError(res.error.message);
        setSaving(false);
        return;
      }
      reset();
      router.refresh();
    } catch {
      setError('Falha de rede. Tente novamente.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded border border-slate-200 p-3 dark:border-slate-800"
    >
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Adicionar registro
      </h2>

      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
          Tipo
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as AddKind)}
            className="mt-0.5 rounded border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          >
            <option value="food">Comida</option>
            <option value="water">Água</option>
            <option value="beverage">Bebida calórica</option>
            <option value="activity">Atividade</option>
          </select>
        </label>

        {kind !== 'water' && (
          <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
            Nome
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-0.5 w-40 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
        )}

        {kind !== 'activity' && (
          <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
            {kind === 'food' ? 'Gramas' : 'Volume (ml)'}
            <input
              type="number"
              min="1"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="mt-0.5 w-24 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
        )}

        {kind === 'food' && (
          <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
            Refeição
            <select
              value={mealSlot}
              onChange={(e) => setMealSlot(e.target.value)}
              className="mt-0.5 rounded border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            >
              {MEAL_SLOTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        )}

        {kind === 'activity' && (
          <>
            <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
              Tipo
              <select
                value={activityType}
                onChange={(e) => setActivityType(e.target.value)}
                className="mt-0.5 rounded border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              >
                {ACTIVITY_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
              Duração (min)
              <input
                type="number"
                min="1"
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                className="mt-0.5 w-24 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </label>
          </>
        )}

        <button
          type="submit"
          disabled={saving}
          className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white transition disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {saving ? 'Adicionando…' : 'Adicionar'}
        </button>
      </div>

      {error && (
        <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </form>
  );
}
