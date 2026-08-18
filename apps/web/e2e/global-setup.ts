/**
 * Guarda de stack — roda uma vez antes de qualquer spec.
 *
 * O Playwright não sobe a stack (docker-compose.e2e.yml) por conta própria;
 * o operador roda `./scripts/e2e-bootstrap.sh` antes. Este setup falha
 * rápido com instrução clara se api/web não estiverem respondendo, em vez
 * de deixar a suíte inteira morrer com "error: connect ECONNREFUSED".
 */
import { API_BASE, WEB_BASE } from './support/constants';

const CHECKS = [
  { name: 'API', url: `${API_BASE}/health` },
  { name: 'Web', url: `${WEB_BASE}/login` },
];

export default async function globalSetup(): Promise<void> {
  for (const check of CHECKS) {
    try {
      const res = await fetch(check.url, { signal: AbortSignal.timeout(5000) });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (err) {
      const reason = err instanceof Error && err.name === 'TimeoutError'
        ? 'timed out'
        : String(err);
      throw new Error(
        `E2E: ${check.name} indisponível em ${check.url} (${reason}).\n` +
          `A stack E2E não está no ar. Rode antes:\n` +
          `  ./scripts/e2e-bootstrap.sh        # sobe api+web dev isolados\n` +
          `  ./scripts/e2e-bootstrap.sh --down # desmonta quando terminar`,
      );
    }
  }
}