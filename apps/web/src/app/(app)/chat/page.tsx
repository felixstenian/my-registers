'use client';

import {
  DragEvent,
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { api } from '@/lib/api-client';
import { AssistantContent } from './AssistantContent';
import { CloseDayModal } from './CloseDayModal';
import { DayTotalsBar } from './DayTotalsBar';

type MediaRef = {
  id: string;
  content_type: string;
  url: string;
};

type Message = {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string | null;
  llm_intent: string | null;
  llm_confidence: number | null;
  media: MediaRef[];
  created_at: string;
  // SP-33: quando `llm_intent='log_nutrition_label'`, botão de confirmação
  // aparece embaixo do balão e chama `PATCH /nutrient-facts/{id}`.
  nutrient_fact_id?: string | null;
};

type UploadOk = { ok: true; id: string };
type UploadErr = { ok: false; file: string; reason: string };
type UploadResult = UploadOk | UploadErr;

const MAX_FILES = 4;
// Deve refletir o allowlist do backend (`MediaService.upload`).
const ACCEPT_MIME = ['image/jpeg', 'image/png', 'image/webp'];
const ACCEPT_ATTR = 'image/png,image/jpeg,image/webp';
// SP-18: cap de 8 MB por arquivo (idêntico ao backend). Bloqueamos no
// anexo para dar feedback imediato — o backend também rejeita, mas
// dependendo do proxy do Next.js, arquivos gigantes podem falhar antes
// mesmo do backend responder um JSON de erro.
const MAX_FILE_BYTES = 8 * 1024 * 1024;
const POLL_INTERVAL_MS = 1500;
// Sonnet com imagem + retry semântico pode passar dos 30s. 60s cobre
// >99% dos casos e ainda dá timeout gracioso.
const POLL_CAP_MS = 60_000;

const UPLOAD_REASONS: Record<string, (name: string) => string> = {
  file_too_large: (name) => `\`${name}\` é maior que 8 MB e não pode ser enviada. Reduza a qualidade ou tire outra.`,
  invalid_image: (name) => `\`${name}\` não parece ser uma imagem válida.`,
  unsupported_media_type: (name) =>
    `Formato de \`${name}\` não suportado. Envie JPEG, PNG ou WEBP.`,
  empty_upload: (name) => `\`${name}\` está vazia.`,
};

async function uploadMedia(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
  // FE-01: fetch próprio (FormData/multipart não passa pelo api-client).
  // Lança em falha de rede — capturamos aqui para não virar unhandled
  // rejection dentro de performSend (que não tem try/catch no loop).
  let res: Response;
  try {
    res = await fetch('/api/media', {
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      body: form,
    });
  } catch {
    return {
      ok: false,
      file: file.name,
      reason: `Não foi possível enviar \`${file.name}\` (falha de rede). Verifique sua conexão.`,
    };
  }
  if (res.status === 201) {
    const body = (await res.json()) as { id: string };
    return { ok: true, id: body.id };
  }
  let code = 'upload_failed';
  try {
    const body = (await res.json()) as { code?: string };
    if (body.code) code = body.code;
  } catch {
    // resposta sem json
  }
  const reason =
    UPLOAD_REASONS[code]?.(file.name) ??
    `Não foi possível enviar \`${file.name}\`. Tente novamente.`;
  return { ok: false, file: file.name, reason };
}

function TypingIndicator() {
  return (
    <div
      aria-live="polite"
      aria-label="Assistente digitando"
      className="mr-auto flex max-w-[80%] items-center gap-1 rounded-2xl bg-slate-100 px-4 py-3 dark:bg-slate-800"
    >
      <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]" />
      <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]" />
      <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400" />
    </div>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const [awaitingAssistant, setAwaitingAssistant] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // SP-17/18: erros por arquivo (uma linha por rejeição).
  const [fileErrors, setFileErrors] = useState<string[]>([]);
  // SP-19: feedback visual do dropzone.
  const [isDragging, setIsDragging] = useState(false);
  // Contador para lidar com dragenter/dragleave em elementos filhos (evita
  // "flicker" do feedback ao passar por cima de texto/botão dentro do form).
  const dragCounterRef = useRef(0);
  // SP-33: nutrient_fact_ids que já foram confirmados nesta sessão de UI.
  const [confirmedFacts, setConfirmedFacts] = useState<Set<string>>(new Set());
  // SP-116: signal para o DayTotalsBar revalidar. Incrementa a cada nova
  // assistant message chegando pelo poll (ou pós-ação em modal).
  const [totalsRevalidateKey, setTotalsRevalidateKey] = useState(0);
  // T-704: modal de encerramento aberto com a data-alvo (`YYYY-MM-DD`).
  const [closingDate, setClosingDate] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollStartRef = useRef<number | null>(null);
  const lastIdRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadInitial = useCallback(async () => {
    const result = await api<{ messages: Message[] }>('/chat/messages?limit=100');
    if (result.ok) {
      setMessages(result.data.messages);
      const last = result.data.messages.at(-1);
      lastIdRef.current = last?.id ?? null;
    }
  }, []);

  useEffect(() => {
    loadInitial();
  }, [loadInitial]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, awaitingAssistant]);

  const stopPolling = useCallback((reason?: 'timeout') => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    pollStartRef.current = null;
    setAwaitingAssistant(false);
    if (reason === 'timeout') {
      setError(
        'A resposta demorou mais do que o esperado. Ela ainda pode chegar — atualize a tela em alguns segundos.',
      );
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollStartRef.current = Date.now();
    setAwaitingAssistant(true);

    const tick = async (): Promise<boolean> => {
      const anchor = lastIdRef.current;
      const query = anchor ? `?after=${encodeURIComponent(anchor)}` : '';
      const result = await api<{ messages: Message[] }>(`/chat/messages${query}`);
      if (result.ok && result.data.messages.length > 0) {
        setMessages((prev) => [...prev, ...result.data.messages]);
        const last = result.data.messages.at(-1);
        if (last) lastIdRef.current = last.id;
        const gotAssistant = result.data.messages.some((m) => m.role === 'assistant');
        if (gotAssistant) {
          // SP-116: dispara revalidação da barra de totais.
          setTotalsRevalidateKey((k) => k + 1);
          stopPolling();
          return true;
        }
      }
      if (pollStartRef.current && Date.now() - pollStartRef.current > POLL_CAP_MS) {
        stopPolling('timeout');
        return true;
      }
      return false;
    };

    // Poll imediato para não perder resposta que já chegou dentro do
    // primeiro `POLL_INTERVAL_MS`; depois cai no ciclo normal.
    void tick().then((done) => {
      if (done) return;
      pollRef.current = setInterval(tick, POLL_INTERVAL_MS);
    });
  }, [stopPolling]);

  useEffect(() => stopPolling, [stopPolling]);

  // ---------------------------------------------------------------------
  // SP-17 / SP-18 / SP-19 — normalização de arquivos anexados
  // ---------------------------------------------------------------------
  //
  // `mode='replace'`: nova seleção via `<input type="file">` substitui os
  // pré-anexados (semântica nativa do input).
  //
  // `mode='append'`: drag-and-drop acumula em cima do que já está anexado.
  //
  // Em ambos:
  // - MIME fora do allowlist → linha de erro amigável (SP-18).
  // - Tamanho > 8 MB → linha de erro amigável (SP-18).
  // - Estouro do cap de 4 → nome de cada arquivo rejeitado listado (SP-17).
  const mergeFiles = useCallback(
    (incoming: File[], mode: 'replace' | 'append') => {
      const errs: string[] = [];
      const allowed: File[] = [];
      const rejectedByMime: File[] = [];
      const rejectedBySize: File[] = [];
      for (const file of incoming) {
        if (!ACCEPT_MIME.includes(file.type)) {
          rejectedByMime.push(file);
          continue;
        }
        // SP-18: cap de 8 MB — mesma linha amigável do backend.
        if (file.size > MAX_FILE_BYTES) {
          rejectedBySize.push(file);
          continue;
        }
        allowed.push(file);
      }
      for (const file of rejectedByMime) {
        errs.push(UPLOAD_REASONS.unsupported_media_type(file.name));
      }
      for (const file of rejectedBySize) {
        errs.push(UPLOAD_REASONS.file_too_large(file.name));
      }

      const base = mode === 'append' ? files : [];
      const total = base.length + allowed.length;
      const overflow = Math.max(0, total - MAX_FILES);
      const acceptedFromIncoming = allowed.slice(0, allowed.length - overflow);
      const rejectedFromCap = allowed.slice(allowed.length - overflow);

      if (rejectedFromCap.length > 0) {
        const names = rejectedFromCap.map((f) => `\`${f.name}\``).join(', ');
        errs.push(
          `Limite de ${MAX_FILES} anexos por mensagem — ${names} ${
            rejectedFromCap.length === 1 ? 'não foi anexada' : 'não foram anexadas'
          }.`,
        );
      }

      setFiles([...base, ...acceptedFromIncoming]);
      if (errs.length > 0) {
        setFileErrors(errs);
      } else {
        setFileErrors([]);
      }
    },
    [files],
  );

  const removeFileAt = useCallback((idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
    setFileErrors([]);
  }, []);

  // SP-33: PATCH /nutrient-facts/{id} sem corpo (só marca verified=true).
  // Não fecha o cartão — apenas troca o botão para "Confirmado ✓".
  const confirmNutrientFact = useCallback(async (id: string) => {
    const result = await api(`/nutrient-facts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({}),
    });
    if (result.ok) {
      setConfirmedFacts((prev) => {
        const next = new Set(prev);
        next.add(id);
        return next;
      });
    }
  }, []);

  // ---------------------------------------------------------------------
  // Envio
  // ---------------------------------------------------------------------

  async function performSend() {
    setError(null);
    const trimmed = text.trim();
    if (!trimmed && files.length === 0) {
      setError('Digite algo ou anexe uma imagem.');
      return;
    }
    setSending(true);
    try {
      // SP-18: não aborta o batch por causa de 1 arquivo — sobe todos e
      // apenas os que falharem aparecem em `fileErrors`.
      const mediaIds: string[] = [];
      const uploadErrs: string[] = [];
      for (const file of files) {
        const result = await uploadMedia(file);
        if (result.ok) {
          mediaIds.push(result.id);
        } else {
          uploadErrs.push(result.reason);
        }
      }
      if (uploadErrs.length > 0) {
        setFileErrors(uploadErrs);
      }
      if (mediaIds.length === 0 && !trimmed) {
        // Nada válido para enviar.
        setSending(false);
        return;
      }
      const result = await api<{ message_id: string }>('/chat/messages', {
        method: 'POST',
        body: JSON.stringify({
          text: trimmed || null,
          media_ids: mediaIds,
        }),
      });
      if (!result.ok) {
        setError(result.error.message || 'Falha ao enviar mensagem.');
        return;
      }
      setText('');
      setFiles([]);
      if (uploadErrs.length === 0) {
        setFileErrors([]);
      }
      if (fileInputRef.current) fileInputRef.current.value = '';
      await loadInitial();
      startPolling();
    } finally {
      setSending(false);
    }
  }

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void performSend();
  };

  // SP-15: Enter envia, Shift+Enter quebra linha, envio ignora tecla se
  // já está no meio de outro envio ou o composer está vazio.
  const onTextareaKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter') return;
    // Composição IME (chinês/japonês/coreano) — não interfere.
    if (event.nativeEvent.isComposing) return;
    if (event.shiftKey) return;
    event.preventDefault();
    if (sending) return;
    const canSend = text.trim().length > 0 || files.length > 0;
    if (!canSend) return;
    void performSend();
  };

  // SP-19: drag-and-drop no compositor.
  const onDragEnter = (event: DragEvent<HTMLFormElement>) => {
    if (!event.dataTransfer.types.includes('Files')) return;
    event.preventDefault();
    dragCounterRef.current += 1;
    setIsDragging(true);
  };
  const onDragOver = (event: DragEvent<HTMLFormElement>) => {
    if (!event.dataTransfer.types.includes('Files')) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  };
  const onDragLeave = (event: DragEvent<HTMLFormElement>) => {
    if (!event.dataTransfer.types.includes('Files')) return;
    event.preventDefault();
    dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
    if (dragCounterRef.current === 0) setIsDragging(false);
  };
  const onDrop = (event: DragEvent<HTMLFormElement>) => {
    if (!event.dataTransfer.types.includes('Files')) return;
    event.preventDefault();
    dragCounterRef.current = 0;
    setIsDragging(false);
    const dropped = Array.from(event.dataTransfer.files);
    if (dropped.length === 0) return;
    mergeFiles(dropped, 'append');
  };

  return (
    <main className="mx-auto flex h-[calc(100dvh-49px)] max-w-3xl flex-col gap-2 p-4 pb-[calc(env(safe-area-inset-bottom)+3.5rem)] md:pb-4">
      <DayTotalsBar
        revalidateKey={totalsRevalidateKey}
        onCloseDayClick={(date) => setClosingDate(date)}
      />
      {closingDate !== null && (
        <CloseDayModal
          date={closingDate}
          onClose={() => setClosingDate(null)}
          onClosed={() => setTotalsRevalidateKey((k) => k + 1)}
        />
      )}
      <div className="flex-1 space-y-3 overflow-y-auto rounded border border-slate-200 p-4 dark:border-slate-800">
        {messages.length === 0 && (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Nenhuma mensagem ainda. Envie algo abaixo — texto ou foto.
          </p>
        )}
        {messages.map((m) => {
          const isUser = m.role === 'user';
          return (
            <div
              key={m.id}
              className={
                isUser
                  ? 'ml-auto max-w-[80%] rounded-2xl bg-slate-900 px-3 py-2 text-sm text-white dark:bg-slate-100 dark:text-slate-900'
                  : 'mr-auto max-w-[90%] rounded-2xl bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800'
              }
            >
              {m.content && (
                isUser ? (
                  <p className="whitespace-pre-wrap">{m.content}</p>
                ) : (
                  <AssistantContent content={m.content} />
                )
              )}
              {m.media.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {m.media.map((media) => (
                    <img
                      key={media.id}
                      src={media.url}
                      alt=""
                      className="max-h-40 rounded border border-slate-300 dark:border-slate-700"
                    />
                  ))}
                </div>
              )}
              {!isUser && m.llm_intent === 'log_nutrition_label' && m.nutrient_fact_id && (
                <div className="mt-3 border-t border-slate-300 pt-2 text-xs dark:border-slate-700">
                  {confirmedFacts.has(m.nutrient_fact_id) ? (
                    <span className="font-medium text-emerald-700 dark:text-emerald-400">
                      Confirmado ✓
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => confirmNutrientFact(m.nutrient_fact_id!)}
                      className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white transition hover:bg-emerald-700"
                    >
                      Confirmar cadastro do produto
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {awaitingAssistant && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={onSubmit}
        onDragEnter={onDragEnter}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={
          'flex flex-col gap-2 rounded border-2 border-dashed p-2 transition-colors ' +
          (isDragging
            ? 'border-slate-500 bg-slate-50 dark:bg-slate-800/50'
            : 'border-transparent')
        }
      >
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onTextareaKeyDown}
          placeholder="Ex.: 150 g de arroz e 180 g de frango grelhado no almoço. (Enter envia, Shift+Enter quebra linha.)"
          rows={2}
          className="w-full resize-none rounded border border-slate-300 bg-white p-2 text-sm outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-900"
        />

        {files.length > 0 && (
          <ul className="flex flex-wrap gap-2 text-xs text-slate-600 dark:text-slate-300">
            {files.map((file, idx) => (
              <li
                key={`${file.name}-${idx}`}
                className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1 dark:bg-slate-800"
              >
                <span className="max-w-[12rem] truncate">{file.name}</span>
                <button
                  type="button"
                  onClick={() => removeFileAt(idx)}
                  aria-label={`Remover ${file.name}`}
                  className="text-slate-500 hover:text-slate-800 dark:hover:text-slate-100"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex items-center gap-2 text-sm">
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT_ATTR}
            // SP-16: no mobile, sugere abrir câmera traseira (foto de prato/rótulo).
            // O atributo é ignorado por browsers desktop.
            capture="environment"
            multiple
            onChange={(e) => {
              const list = Array.from(e.target.files ?? []);
              mergeFiles(list, 'replace');
              // Permite selecionar o mesmo arquivo novamente após remover.
              e.target.value = '';
            }}
            className="text-xs"
          />
          {files.length > 0 && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {files.length}/{MAX_FILES} anexado{files.length > 1 ? 's' : ''}
            </span>
          )}
          <button
            type="submit"
            disabled={sending}
            className="ml-auto rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white transition disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900"
          >
            {sending ? 'Enviando…' : 'Enviar'}
          </button>
        </div>

        {fileErrors.length > 0 && (
          <ul role="alert" className="space-y-1 text-xs text-amber-700 dark:text-amber-400">
            {fileErrors.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        )}

        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
      </form>

      <footer className="text-center text-xs text-slate-500 dark:text-slate-400">
        As estimativas nutricionais desta ferramenta são aproximações e não substituem
        acompanhamento médico ou nutricional.
      </footer>
    </main>
  );
}
