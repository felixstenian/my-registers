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
  const res = await fetch(`/api${path}`, {
    ...init,
    credentials: 'include',
    cache: 'no-store',
    headers,
  });

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
    const err = (body ?? DEFAULT_ERROR) as ApiError;
    return { ok: false, error: err, status };
  }
  return { ok: true, data: body as T, status };
}
