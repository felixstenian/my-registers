// SP-150..SP-154 — shape do `GET /days/today` consumido pela página /day.
// Espelha `DaySnapshotOut` (backend) + o dicionário rico de `_load_food`
// (ver `apps/api/app/services/day_query.py::_load_food`).

export type MealSlot =
  | 'breakfast'
  | 'lunch'
  | 'snack'
  | 'dinner'
  | 'unspecified';

export interface FoodItem {
  id: string;
  detected_name: string;
  grams: number | null;
  ml: number | null;
  quantity: number | null;
  unit: string | null;
  kcal: number | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
  // Micros (SP-152 — expansão).
  sodium_mg: number | null;
  calcium_mg: number | null;
  iron_mg: number | null;
  potassium_mg: number | null;
  // Metadata.
  confidence: number | null;
  has_catalog: boolean;
  is_estimate: boolean;
  source: string;
}

export interface FoodRecord {
  id: string;
  meal_slot: MealSlot;
  occurred_at: string;
  items: FoodItem[];
}

export interface WaterRecord {
  id: string;
  volume_ml: number;
  occurred_at: string;
}

export interface BeverageRecord {
  id: string;
  detected_name: string;
  volume_ml: number;
  kcal: number | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  occurred_at: string;
}

export interface ActivityRecord {
  id: string;
  detected_name: string;
  activity_type: string;
  duration_minutes: number | null;
  intensity: string | null;
  kcal_burned: number | null;
  calc_method: string;
  occurred_at: string;
}

export interface DayTotals {
  kcal_in: number;
  kcal_out: number;
  kcal_balance: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  sodium_mg: number;
  calcium_mg: number;
  iron_mg: number;
  potassium_mg: number;
  water_ml: number;
  other_liquids_ml: number;
}

export interface DaySnapshot {
  date: string; // YYYY-MM-DD
  status: 'open' | 'closed';
  closed_at: string | null;
  totals: DayTotals;
  records: {
    food: FoodRecord[];
    water: WaterRecord[];
    beverage: BeverageRecord[];
    activity: ActivityRecord[];
  };
  warnings: Array<Record<string, unknown>>;
  narrative: string | null;
  snapshot_version: number;
}

// Ordem canônica para renderização (SP-151).
export const MEAL_SLOT_ORDER: MealSlot[] = [
  'breakfast',
  'lunch',
  'snack',
  'dinner',
  'unspecified',
];

export const MEAL_SLOT_LABEL_PT: Record<MealSlot, string> = {
  breakfast: 'Café da manhã',
  lunch: 'Almoço',
  snack: 'Lanche',
  dinner: 'Jantar',
  unspecified: 'Outros',
};

export const ACTIVITY_TYPE_LABEL_PT: Record<string, string> = {
  cardio_walk: 'Caminhada',
  cardio_run: 'Corrida',
  cardio_bike: 'Ciclismo',
  cardio_swim: 'Natação',
  strength: 'Musculação',
  hiit: 'HIIT',
  yoga: 'Yoga',
  pilates: 'Pilates',
  other: 'Outra',
};

export const CALC_METHOD_LABEL_PT: Record<string, string> = {
  met_estimate: 'estimado por MET',
  reported_by_device: 'informado pelo dispositivo',
  workout_session: 'sessão de treino',
};

export const SOURCE_LABEL_PT: Record<string, string> = {
  llm: 'LLM',
  user_corrected: 'corrigido',
  label_ocr: 'rótulo (foto)',
  user_manual: 'manual',
};
