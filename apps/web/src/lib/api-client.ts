// FE-04: guard anti-redirect-loop. Quando a sessão expira, múltiplas
// chamadas concorrentes (poll + DayTotalsBar revalidação) recebem 401
// ao mesmo tempo e cada uma tentaria `window.location.assign`. Após o
// primeiro redirect a página recarrega (novo contexto JS), então a flag
// só precisa viver entre as chamadas da mesma página.
let isRedirectingToLogin = false;

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
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('content-type')) {
    headers.set('content-type', 'application/json');
  }
  // Cache off: o chat depende de poll bater na mesma URL enquanto o
  // assistant não chega. Sem `no-store`, o browser pode servir a resposta
  // vazia da chamada anterior do cache e a mensagem só aparece no refresh.
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
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
    // FE-04: 401 em path que não seja `/auth/*` indica cookie de sessão
    // expirado/inválido. O proxy só checa presença do cookie, não validade,
    // então sem este redirect o chat para de carregar e nada leva o usuário
    // de volta ao login. `/auth/*` (login, logout) é excluído: o LoginForm
    // exibe "credenciais inválidas" e o logout não precisa redirecionar.
    if (
      status === 401 &&
      !path.startsWith('/auth/') &&
      typeof window !== 'undefined' &&
      !isRedirectingToLogin
    ) {
      isRedirectingToLogin = true;
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
