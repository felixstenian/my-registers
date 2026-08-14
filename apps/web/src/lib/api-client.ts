// FE-04: guard anti-redirect-loop. Quando a sessão expira, múltiplas
// chamadas concorrentes (poll + DayTotalsBar revalidação) recebem 401
// ao mesmo tempo e cada uma tentaria `window.location.assign`. Após o
// primeiro redirect a página recarrega (novo contexto JS), então a flag
// só precisa viver entre as chamadas da mesma página.
//
// Usamos `globalThis` em vez de `let` no escopo do módulo porque o
// Next.js dev mode (webpack) pode criar múltiplas instâncias do módulo
// (uma por chunk de cliente), cada uma com sua própria cópia da flag.
// `globalThis` garante singleton real entre todas as instâncias.
const REDIRECT_GUARD_KEY = '__mr_redirectingToLogin' as const;
function isRedirectingToLogin(): boolean {
  return (globalThis as Record<string, unknown>)[REDIRECT_GUARD_KEY] === true;
}
function setRedirectingToLogin(): void {
  (globalThis as Record<string, unknown>)[REDIRECT_GUARD_KEY] = true;
}

// FE-05: sessão expirada → tenta /auth/refresh antes de deslogar. Sem
// este passo, o access token de 15 min (JWT_ACCESS_TTL_SECONDS=900) sempre
// terminava em logout forçado a cada 15 minutos.
//
// Single-flight: chamadas concorrentes (poll + revalidação do DayTotalsBar)
// que recebem 401 ao mesmo tempo compartilham a MESMA promise de refresh.
// Isso é obrigatório porque o refresh rotaciona o token (Const. §17): dois
// POSTs paralelos com o mesmo refresh token fariam o segundo disparar a
// invalidação de família (`revoke_family`) e matar a sessão inteira (BE-05).
//
// Assim como o REDIRECT_GUARD_KEY, usamos `globalThis` em vez de `let` no
// escopo do módulo para o single-flight sobreviver às múltiplas instâncias
// do módulo que o Next.js webpack dev mode cria (uma por chunk de cliente).
const REFRESH_SINGLE_FLIGHT_KEY = '__mr_refreshSingleFlight' as const;
function getRefreshSingleFlight(): Promise<boolean> | null {
  const value = (globalThis as Record<string, unknown>)[REFRESH_SINGLE_FLIGHT_KEY];
  return value instanceof Promise ? (value as Promise<boolean>) : null;
}
function setRefreshSingleFlight(p: Promise<boolean> | null): void {
  (globalThis as Record<string, unknown>)[REFRESH_SINGLE_FLIGHT_KEY] = p;
}

async function tryRefreshSession(): Promise<boolean> {
  let flight = getRefreshSingleFlight();
  if (flight === null) {
    flight = (async () => {
      try {
        const res = await fetch('/api/auth/refresh', {
          method: 'POST',
          credentials: 'include',
          cache: 'no-store',
        });
        return res.ok;
      } catch {
        return false;
      } finally {
        setRefreshSingleFlight(null);
      }
    })();
    setRefreshSingleFlight(flight);
  }
  return flight;
}

export type ApiError = {
  code: string;
  message: string;
};

export type ApiResult<T> =
  | { ok: true; data: T; status: number }
  | { ok: false; error: ApiError; status: number };

const DEFAULT_ERROR: ApiError = { code: 'unknown', message: 'Erro desconhecido' };

export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  const { __isRetry = false, ...fetchInit } = init as RequestInit & { __isRetry?: boolean };
  const headers = new Headers(fetchInit.headers);
  if (fetchInit.body && !headers.has('content-type')) {
    headers.set('content-type', 'application/json');
  }
  // Cache off: o chat depende de poll bater na mesma URL enquanto o
  // assistant não chega. Sem `no-store`, o browser pode servir a resposta
  // vazia da chamada anterior do cache e a mensagem só aparece no refresh.
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...fetchInit,
      credentials: 'include',
      cache: 'no-store',
      headers,
    });
  } catch {
    // FE-01: fetch lança (não rejeita com status) quando a rede falha
    // (offline, backend fora, DNS/CORS). Sem este catch, todo chamador
    // sem try/catch próprio vira unhandled rejection e trava em loading.
    // Retornamos o ramo `!ok` para que os chamadores existentes tratem.
    return {
      ok: false,
      error: { code: 'network_error', message: 'Falha de rede. Verifique sua conexão.' },
      status: 0,
    };
  }

  const status = res.status;
  if (status === 204) {
    return { ok: true, data: undefined as unknown as T, status };
  }

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }

  if (!res.ok) {
    // FE-04 + FE-05: 401 em path que não seja `/auth/*` indica cookie de
    // sessão expirado/inválido. O proxy só checa presença do cookie, não
    // validade. Antes de deslogar, tenta `POST /auth/refresh` (o access
    // token dura 15 min; o refresh token, 14 dias). Só se o refresh
    // falhar é que o usuário é deslogado e levado ao login.
    // `/auth/*` (login, logout) é excluído: o LoginForm exibe "credenciais
    // inválidas" e o logout não precisa redirecionar.
    if (
      status === 401 &&
      !path.startsWith('/auth/') &&
      typeof window !== 'undefined' &&
      !isRedirectingToLogin()
    ) {
      const refreshed = await tryRefreshSession();
      if (refreshed && !__isRetry) {
        // Cookie novo já foi setado pelo backend; repete o request original
        // uma única vez com o access token renovado. O flag `__isRetry`
        // impede loop infinito caso o próprio refresh retorne 401.
        const retryInit = { ...fetchInit, __isRetry: true } as RequestInit & {
          __isRetry?: boolean;
        };
        return api(path, retryInit);
      }
      setRedirectingToLogin();
      // O cookie de sessão é HttpOnly — não dá para limpar via
      // `document.cookie`. Sem invalidar, o proxy (`proxy.ts:24`) rebate
      // `/login` de volta pra `/chat` (presença de cookie ≠ válido). Um
      // POST best-effort para /auth/logout faz o backend emitir
      // `Set-Cookie: access_token=; Max-Age=0` antes do redirect.
      void fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).finally(() => {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.assign(`/login?next=${next}`);
      });
    }
    const err = (body ?? DEFAULT_ERROR) as ApiError;
    return { ok: false, error: err, status };
  }
  return { ok: true, data: body as T, status };
}
