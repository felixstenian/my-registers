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
