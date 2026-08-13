'use client';

// SP-167/168 — Formulários de edição inline para /day.
// Client components usando `api()` de api-client.ts (padrão FE-04).
// `router.refresh()` após sucesso re-renderiza server components.

import { api, type ApiResult } from '@/lib/api-client';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

// ---------------------------------------------------------------------------
// Shared hook
// ---------------------------------------------------------------------------

type EditState = 'idle' | 'saving' | 'error';

function useEditForm() {
  const router = useRouter();
  const [state, setState] = useState<EditState>('idle');
  const [errorMsg, setErrorMsg] = useState<string>('');

  async function submit<T>(
    path: string,
    body: Record<string, unknown>,
    onSuccess?: (data: T) => void,
  ): Promise<boolean> {
    setState('saving');
    setErrorMsg('');
    const res: ApiResult<T> = await api<T>(path, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
    if (res.ok) {
      setState('idle');
      onSuccess?.(res.data);
      router.refresh();
      return true;
    }
    setState('error');
    setErrorMsg(res.error.message);
    return false;
  }

  return { state, errorMsg, submit };
}

// ---------------------------------------------------------------------------
// EditFoodItemForm — SP-167
// ---------------------------------------------------------------------------

import type { FoodItem } from './types';

const EDITABLE_FACT_SOURCES = ['label_ocr', 'manual'] as const;

export function EditFoodItemForm({
  item,
  dayClosed,
}: {
  item: FoodItem;
  dayClosed: boolean;
}) {
  const { state, errorMsg, submit } = useEditForm();
  const [grams, setGrams] = useState(item.grams?.toString() ?? '');
  const [ml, setMl] = useState(item.ml?.toString() ?? '');
  const [factKcal, setFactKcal] = useState(item.fact_kcal?.toString() ?? '');
  const [factProtein, setFactProtein] = useState(item.fact_protein_g?.toString() ?? '');
  const [factCarbs, setFactCarbs] = useState(item.fact_carbs_g?.toString() ?? '');
  const [factFat, setFactFat] = useState(item.fact_fat_g?.toString() ?? '');

  if (dayClosed) {
    return (
      <p className="mt-2 text-[11px] italic text-slate-500 dark:text-slate-400">
        Dia encerrado — não é possível editar.
      </p>
    );
  }

  const factEditable =
    item.catalog_ref_id !== null &&
    item.fact_source !== null &&
    EDITABLE_FACT_SOURCES.includes(item.fact_source as (typeof EDITABLE_FACT_SOURCES)[number]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    // Step 1: If per-100g values changed, PATCH the nutrient_fact first
    // (triggers propagation which recomputes this item's macros).
    if (factEditable && item.catalog_ref_id) {
      const factBody: Record<string, unknown> = {};
      const k = parseFloat(factKcal);
      const p = parseFloat(factProtein);
      const c = parseFloat(factCarbs);
      const f = parseFloat(factFat);
      if (!isNaN(k) && k !== item.fact_kcal) factBody.kcal = k;
      if (!isNaN(p) && p !== item.fact_protein_g) factBody.protein_g = p;
      if (!isNaN(c) && c !== item.fact_carbs_g) factBody.carbs_g = c;
      if (!isNaN(f) && f !== item.fact_fat_g) factBody.fat_g = f;
      if (Object.keys(factBody).length > 0) {
        const ok = await submit(`/nutrient-facts/${item.catalog_ref_id}`, factBody);
        if (!ok) return;
      }
    }

    // Step 2: If quantity changed, PATCH the food_item
    // (recomputes macros from the now-updated fact values).
    const itemBody: Record<string, unknown> = {};
    const g = parseFloat(grams);
    const m = parseFloat(ml);
    if (!isNaN(g) && g > 0) itemBody.grams = g;
    if (!isNaN(m) && m > 0) itemBody.ml = m;
    if (Object.keys(itemBody).length > 0) {
      await submit(`/records/food-items/${item.id}`, itemBody);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="m-2 space-y-2 flex flex-wrap items-end gap-2">
        <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
          Gramas
          <input
            type="number"
            step="any"
            min="0"
            value={grams}
            onChange={(e) => setGrams(e.target.value)}
            placeholder={item.grams ? String(item.grams) : '—'}
            className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          />
        </label>
        <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
          ml
          <input
            type="number"
            step="any"
            min="0"
            value={ml}
            onChange={(e) => setMl(e.target.value)}
            placeholder={item.ml ? String(item.ml) : '—'}
            className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          />
        </label>
      </div>

      {factEditable && (
        <div className="border-l border-slate-100 pl-2 dark:border-slate-800">
          <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-400">
            Valores por 100g (rótulo)
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
              Calorias
              <input
                type="number"
                step="any"
                min="0"
                value={factKcal}
                onChange={(e) => setFactKcal(e.target.value)}
                placeholder={item.fact_kcal ? String(item.fact_kcal) : '—'}
                className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </label>
            <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
              Proteína
              <input
                type="number"
                step="any"
                min="0"
                value={factProtein}
                onChange={(e) => setFactProtein(e.target.value)}
                placeholder={item.fact_protein_g ? String(item.fact_protein_g) : '—'}
                className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </label>
            <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
              Carboidratos
              <input
                type="number"
                step="any"
                min="0"
                value={factCarbs}
                onChange={(e) => setFactCarbs(e.target.value)}
                placeholder={item.fact_carbs_g ? String(item.fact_carbs_g) : '—'}
                className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </label>
            <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
              Gordura
              <input
                type="number"
                step="any"
                min="0"
                value={factFat}
                onChange={(e) => setFactFat(e.target.value)}
                placeholder={item.fact_fat_g ? String(item.fact_fat_g) : '—'}
                className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </label>
          </div>
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={state === 'saving'}
          className="rounded bg-slate-700 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-slate-600 disabled:opacity-50 dark:bg-slate-600 dark:hover:bg-slate-500"
        >
          {state === 'saving' ? 'Salvando…' : 'Salvar'}
        </button>
        {state === 'error' && (
          <span className="text-xs text-red-600 dark:text-red-400">{errorMsg}</span>
        )}
      </div>

      {!factEditable && item.catalog_ref_id !== null && (
        <p className="text-[10px] italic text-slate-400 dark:text-slate-500">
          Catálogo canônico macros não editável
        </p>
      )}
    </form>
  );
}

// ---------------------------------------------------------------------------
// EditWaterForm — SP-168
// ---------------------------------------------------------------------------

import type { WaterRecord } from './types';

export function EditWaterForm({
  record,
  dayClosed,
}: {
  record: WaterRecord;
  dayClosed: boolean;
}) {
  const { state, errorMsg, submit } = useEditForm();
  const [volume, setVolume] = useState(String(record.volume_ml));

  if (dayClosed) return null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const v = parseInt(volume, 10);
    if (isNaN(v) || v <= 0) return;
    await submit(`/records/water/${record.id}`, { volume_ml: v });
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2 pl-2">
      <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
        Volume (ml)
        <input
          type="number"
          min="1"
          value={volume}
          onChange={(e) => setVolume(e.target.value)}
          className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
      </label>
      <button
        type="submit"
        disabled={state === 'saving'}
        className="rounded bg-slate-700 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-slate-600 disabled:opacity-50 dark:bg-slate-600 dark:hover:bg-slate-500"
      >
        {state === 'saving' ? '…' : 'OK'}
      </button>
      {state === 'error' && (
        <span className="text-xs text-red-600 dark:text-red-400">{errorMsg}</span>
      )}
    </form>
  );
}

// ---------------------------------------------------------------------------
// EditBeverageForm — SP-168
// ---------------------------------------------------------------------------

import type { BeverageRecord } from './types';

export function EditBeverageForm({
  record,
  dayClosed,
}: {
  record: BeverageRecord;
  dayClosed: boolean;
}) {
  const { state, errorMsg, submit } = useEditForm();
  const [volume, setVolume] = useState(String(record.volume_ml));

  if (dayClosed) return null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const v = parseInt(volume, 10);
    if (isNaN(v) || v <= 0) return;
    await submit(`/records/beverage/${record.id}`, { volume_ml: v });
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2 pl-2">
      <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
        Volume (ml)
        <input
          type="number"
          min="1"
          value={volume}
          onChange={(e) => setVolume(e.target.value)}
          className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
      </label>
      <button
        type="submit"
        disabled={state === 'saving'}
        className="rounded bg-slate-700 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-slate-600 disabled:opacity-50 dark:bg-slate-600 dark:hover:bg-slate-500"
      >
        {state === 'saving' ? '…' : 'OK'}
      </button>
      {state === 'error' && (
        <span className="text-xs text-red-600 dark:text-red-400">{errorMsg}</span>
      )}
    </form>
  );
}

// ---------------------------------------------------------------------------
// EditActivityForm — SP-168
// ---------------------------------------------------------------------------

import type { ActivityRecord } from './types';

const INTENSITIES = ['light', 'moderate', 'vigorous', 'unknown'] as const;
const INTENSITY_LABEL_PT: Record<string, string> = {
  light: 'Leve',
  moderate: 'Moderada',
  vigorous: 'Vigorosa',
  unknown: 'Desconhecida',
};

export function EditActivityForm({
  record,
  dayClosed,
}: {
  record: ActivityRecord;
  dayClosed: boolean;
}) {
  const { state, errorMsg, submit } = useEditForm();
  const [duration, setDuration] = useState(
    record.duration_minutes ? String(record.duration_minutes) : '',
  );
  const [intensity, setIntensity] = useState(record.intensity ?? 'unknown');
  const [kcalBurned, setKcalBurned] = useState('');

  if (dayClosed) return null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = {};
    const d = parseFloat(duration);
    if (!isNaN(d) && d > 0) body.duration_minutes = d;
    if (intensity !== record.intensity) body.intensity = intensity;
    const k = parseFloat(kcalBurned);
    if (!isNaN(k) && k >= 0) body.kcal_burned = k;
    if (Object.keys(body).length === 0) return;
    await submit(`/records/activity/${record.id}`, body);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mt-1 flex flex-wrap items-end gap-2 border-t border-slate-100 px-3 py-2 dark:border-slate-800"
    >
      <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
        Duração (min)
        <input
          type="number"
          step="any"
          min="0"
          value={duration}
          onChange={(e) => setDuration(e.target.value)}
          className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
      </label>
      <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
        Intensidade
        <select
          value={intensity}
          onChange={(e) => setIntensity(e.target.value)}
          className="mt-0.5 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        >
          {INTENSITIES.map((i) => (
            <option key={i} value={i}>
              {INTENSITY_LABEL_PT[i]}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col text-[11px] text-slate-500 dark:text-slate-400">
        kcal (manual)
        <input
          type="number"
          step="any"
          min="0"
          value={kcalBurned}
          onChange={(e) => setKcalBurned(e.target.value)}
          placeholder={record.kcal_burned ? String(record.kcal_burned) : '—'}
          className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
      </label>
      <button
        type="submit"
        disabled={state === 'saving'}
        className="rounded bg-slate-700 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-slate-600 disabled:opacity-50 dark:bg-slate-600 dark:hover:bg-slate-500"
      >
        {state === 'saving' ? 'Salvando…' : 'Salvar'}
      </button>
      {state === 'error' && (
        <span className="text-xs text-red-600 dark:text-red-400">{errorMsg}</span>
      )}
    </form>
  );
}