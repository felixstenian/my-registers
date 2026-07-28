// Formatters compartilhados pela página /day (SP-150..SP-154).
// Toda formatação pt-BR (vírgula decimal, milhar, meses). Zero é sempre
// renderizado como `—` pra reduzir ruído visual (SP-152).

const nfInt = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
const nfDec1 = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 1,
});
const nfDateFull = new Intl.DateTimeFormat('pt-BR', {
  weekday: 'long',
  day: '2-digit',
  month: 'long',
  year: 'numeric',
});
const nfTime = new Intl.DateTimeFormat('pt-BR', {
  hour: '2-digit',
  minute: '2-digit',
});

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return nfInt.format(n);
}

export function fmtGrams(n: number | null | undefined, unit = 'g'): string {
  if (n === null || n === undefined || n === 0) return '—';
  return `${nfDec1.format(n)} ${unit}`;
}

export function fmtKcal(n: number | null | undefined): string {
  if (n === null || n === undefined || n === 0) return '—';
  return `${nfInt.format(n)} kcal`;
}

export function fmtMg(n: number | null | undefined): string {
  if (n === null || n === undefined || n === 0) return '—';
  return `${nfInt.format(n)} mg`;
}

export function fmtMl(n: number | null | undefined): string {
  if (n === null || n === undefined || n === 0) return '—';
  return `${nfInt.format(n)} ml`;
}

/**
 * ISO YYYY-MM-DD tratado como data local (sem timezone drift). Fallback
 * pra strings vazias em cenários degradados.
 */
export function fmtDateFull(iso: string): string {
  const [y, m, d] = iso.split('-').map((s) => parseInt(s, 10));
  if (!y || !m || !d) return iso;
  return nfDateFull.format(new Date(y, m - 1, d));
}

/**
 * ISO datetime (com timezone) → HH:mm no fuso local do browser. Backend
 * sempre grava com timezone-aware, então isso reflete o horário local
 * do usuário (SP-92).
 */
export function fmtTime(iso: string): string {
  const dt = new Date(iso);
  if (isNaN(dt.getTime())) return '';
  return nfTime.format(dt);
}

export function fmtAmount(
  grams: number | null,
  ml: number | null,
  quantity: number | null,
  unit: string | null,
): string {
  if (grams !== null && grams > 0) return fmtGrams(grams);
  if (ml !== null && ml > 0) return fmtMl(ml);
  if (quantity !== null && quantity > 0) {
    return unit ? `${nfDec1.format(quantity)} ${unit}` : nfDec1.format(quantity);
  }
  return '—';
}

/**
 * Confidence 0..1 → "92%" ou "—" se null.
 */
export function fmtConfidence(c: number | null): string {
  if (c === null || c === undefined) return '—';
  return `${Math.round(c * 100)}%`;
}

// --- Aritmética de datas para navegação temporal (SP-155) ---
//
// Usa UTC interno pra evitar DST drift: o input é YYYY-MM-DD sem hora,
// tratamos como dia calendário. `todayLocalISO` usa o timezone do
// browser, o que casa com o `user.timezone` do backend na maioria dos
// cenários pessoais (contas locais).

export function isoToParts(iso: string): { y: number; m: number; d: number } | null {
  const [y, m, d] = iso.split('-').map((s) => parseInt(s, 10));
  if (!y || !m || !d) return null;
  return { y, m, d };
}

export function partsToIso(y: number, m: number, d: number): string {
  const pad = (n: number) => n.toString().padStart(2, '0');
  return `${y}-${pad(m)}-${pad(d)}`;
}

export function addDaysISO(iso: string, delta: number): string {
  const p = isoToParts(iso);
  if (!p) return iso;
  const dt = new Date(Date.UTC(p.y, p.m - 1, p.d));
  dt.setUTCDate(dt.getUTCDate() + delta);
  return partsToIso(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate());
}

/**
 * ISO YYYY-MM-DD do dia local do browser. Usado como `max` do date
 * picker e como referência pra esconder botão "próximo" quando estamos
 * no dia atual.
 */
export function todayLocalISO(): string {
  const dt = new Date();
  return partsToIso(dt.getFullYear(), dt.getMonth() + 1, dt.getDate());
}

/**
 * Compara YYYY-MM-DD lexicograficamente (funciona porque zero-padded).
 * Retorna -1 / 0 / 1.
 */
export function compareISO(a: string, b: string): number {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}
