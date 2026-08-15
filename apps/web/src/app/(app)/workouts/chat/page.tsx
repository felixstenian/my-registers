'use client';

/**
 * SP-173 (T-B315/T-B317) — chat de treino dedicado.
 *
 * Espelha `(app)/chat/page.tsx` no mesmo pool de `messages` com
 * `via='workout'` (E1): composer + upload de mídia + polling
 * `GET /chat/messages?via=workout&after=` + `AssistantContent`.
 *
 * Diferentes do chat de comida:
 * - Header `WorkoutTotalsHeader` (atividades do dia + kcal gastas), sem
 *   botão "Encerrar dia" (SP-173 — fica no chat de alimentação/modal).
 * - Botões "Cadastrar treino" / "Iniciar treino"; com sessão ativa
 *   (`GET /workouts/session/active`), o botão da direita vira
 *   "Finalizar treino".
 * - Avatar de sessão ativa (SP-179): exibições mínimas para o usuário
 *   saber que há treino em andamento.
 */

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
import { AssistantContent } from '../../chat/AssistantContent';
import { WorkoutHistoryCard } from '../../chat/WorkoutHistoryCard';
import { WorkoutTotalsHeader } from '../WorkoutTotalsHeader';

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
};

type UploadOk = { ok: true; id: string };
type UploadErr = { ok: false; file: string; reason: string };
type UploadResult = UploadOk | UploadErr;

type ActiveSession = {
  id: string;
  workout_type: string | null;
  detected_name: string | null;
  started_at: string | null;
};

const MAX_FILES = 4;
const ACCEPT_MIME = ['image/jpeg', 'image/png', 'image/webp'];
const ACCEPT_ATTR = 'image/png,image/jpeg,image/webp';
const MAX_FILE_BYTES = 8 * 1024 * 1024;
const POLL_INTERVAL_MS = 1500;
const POLL_CAP_MS = 60_000;

const UPLOAD_REASONS: Record<string, (name: string) => string> = {
  file_too_large: (name) =>
    `\`${name}\` é maior que 8 MB e não pode ser enviada. Reduza a qualidade ou tire outra.`,
  invalid_image: (name) => `\`${name}\` não parece ser uma imagem válida.`,
  unsupported_media_type: (name) =>
    `Formato de \`${name}\` não suportado. Envie JPEG, PNG ou WEBP.`,
  empty_upload: (name) => `\`${name}\` está vazia.`,
};

// SP-17/18: cap de 8 MB e allowlist de MIME espelham o backend
// (`MediaService.upload`); bloqueio no anexo dá feedback imediato.
async function uploadMedia(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
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

export default function WorkoutChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const [awaitingAssistant, setAwaitingAssistant] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // T-B317: dica de cadastro exibida ao tocar em "Cadastrar treino".
  const [hint, setHint] = useState<string | null>(null);
  const [fileErrors, setFileErrors] = useState<string[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);
  const [totalsRevalidateKey, setTotalsRevalidateKey] = useState(0);
  // T-B317: sessão ativa muda o botão "Iniciar treino" → "Finalizar treino".
  const [activeSession, setActiveSession] = useState<ActiveSession | null | undefined>(
    undefined,
  );
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollStartRef = useRef<number | null>(null);
  const lastIdRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const loadInitial = useCallback(async () => {
    const result = await api<{ messages: Message[] }>(
      '/chat/messages?via=workout&limit=100',
    );
    if (result.ok) {
      setMessages(result.data.messages);
      const last = result.data.messages.at(-1);
      lastIdRef.current = last?.id ?? null;
    }
  }, []);

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, awaitingAssistant]);

  // T-B317: sessão ativa para o botão Finalizar → revalida quando nova
  // assistant message chega (workout_start/workout_end mudam o estado).
  const refreshActiveSession = useCallback(async () => {
    const result = await api<ActiveSession | null>('/workouts/session/active');
    if (result.ok) {
      setActiveSession(result.data);
    }
  }, []);

  useEffect(() => {
    void refreshActiveSession();
  }, [refreshActiveSession, totalsRevalidateKey]);

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
      const query =
        `via=workout` +
        (anchor ? `&after=${encodeURIComponent(anchor)}` : '');
      const result = await api<{ messages: Message[] }>(`/chat/messages?${query}`);
      if (result.ok && result.data.messages.length > 0) {
        setMessages((prev) => [...prev, ...result.data.messages]);
        const last = result.data.messages.at(-1);
        if (last) lastIdRef.current = last.id;
        const gotAssistant = result.data.messages.some((m) => m.role === 'assistant');
        if (gotAssistant) {
          setTotalsRevalidateKey((k) => k + 1);
          void refreshActiveSession();
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

    void tick().then((done) => {
      if (done) return;
      pollRef.current = setInterval(tick, POLL_INTERVAL_MS);
    });
  }, [stopPolling, refreshActiveSession]);

  useEffect(() => stopPolling, [stopPolling]);

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
      setFileErrors(errs);
    },
    [files],
  );

  const removeFileAt = useCallback((idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
    setFileErrors([]);
  }, []);

  async function performSend(prefill?: string) {
    setError(null);
    setHint(null);
    const trimmed = (prefill ?? text).trim();
    setText('');
    if (!trimmed && files.length === 0) {
      setError('Digite algo ou anexe uma imagem.');
      return;
    }
    setSending(true);
    try {
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
        setSending(false);
        return;
      }
      const result = await api<{ message_id: string }>('/chat/messages', {
        method: 'POST',
        body: JSON.stringify({
          text: trimmed,
          media_ids: mediaIds,
          via: 'workout',
        }),
      });
      if (!result.ok) {
        setError(result.error.message || 'Falha ao enviar mensagem.');
        return;
      }
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

  const onTextareaKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter') return;
    if (event.nativeEvent.isComposing) return;
    if (event.shiftKey) return;
    event.preventDefault();
    if (sending) return;
    const canSend = text.trim().length > 0 || files.length > 0;
    if (!canSend) return;
    void performSend();
  };

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

  // T-B317: "Cadastrar treino" foca o composer com placeholder de cadastro;
  // "Iniciar treino" dispara a mensagem que o backend interpreta como
  // workout_start; com sessão ativa o botão vira "Finalizar treino"
  // (workout_end).
  const onRegisterTemplate = useCallback(() => {
    setHint(
      'Descreva o treino para cadastrá-lo, ex.: "push — supino 3 séries de 10, desenvolvimento 3 séries de 12".',
    );
    textareaRef.current?.focus();
  }, []);

  const startWorkout = useCallback(() => {
    void performSend('iniciar treino');
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const finishWorkout = useCallback(() => {
    void performSend('finalizar treino');
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // T-B319 (SP-178): botão "Ir para o próximo exercício" — re-lista o plano
  // do template ativo (`workout_next_exercise`, Decisão 7).
  const goToNextExercise = useCallback(() => {
    void performSend('ir para o próximo exercício');
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const unknownSession = activeSession === undefined;
  const hasActiveSession = activeSession !== null && activeSession !== undefined;

  return (
    <main className="mx-auto flex h-[calc(100dvh-49px)] max-w-3xl flex-col gap-2 p-4 pb-[calc(env(safe-area-inset-bottom)+3.5rem)] md:pb-4">
      <WorkoutTotalsHeader revalidateKey={totalsRevalidateKey} />
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-slate-500 dark:text-slate-400">
          Chat de treino {hasActiveSession ? '— treino em andamento' : ''}
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={onRegisterTemplate}
            className="rounded border border-slate-300 px-2.5 py-1 font-medium text-slate-700 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Cadastrar treino
          </button>
          {hasActiveSession ? (
            <button
              type="button"
              onClick={finishWorkout}
              className="rounded bg-slate-900 px-2.5 py-1 font-medium text-white transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
            >
              Finalizar treino
            </button>
          ) : (
            <button
              type="button"
              onClick={startWorkout}
              disabled={unknownSession}
              className="rounded bg-slate-900 px-2.5 py-1 font-medium text-white transition disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
            >
              Iniciar treino
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto rounded border border-slate-200 p-4 dark:border-slate-800">
        {messages.length === 0 && (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Nenhum treino registrado ainda. Registre séries, exercícios ou cadastre um treino
            abaixo.
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
              {m.content &&
                (isUser ? (
                  <p className="whitespace-pre-wrap">{m.content}</p>
                ) : m.llm_intent === 'workout_history' ? (
                  <WorkoutHistoryCard content={m.content} />
                ) : (
                  <AssistantContent
                    content={m.content}
                    intent={m.llm_intent}
                    onWorkoutNextExercise={goToNextExercise}
                  />
                ))}
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
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onTextareaKeyDown}
          placeholder="Ex.: supino reto 3×10 com 40 kg. (Enter envia, Shift+Enter quebra linha.)"
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
            capture="environment"
            multiple
            onChange={(e) => {
              const list = Array.from(e.target.files ?? []);
              mergeFiles(list, 'replace');
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

        {hint && !error && (
          <p className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>
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