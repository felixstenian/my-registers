'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api-client';

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

const MAX_FILES = 4;
const POLL_INTERVAL_MS = 1500;
const POLL_CAP_MS = 30_000;

async function uploadMedia(file: File): Promise<string | null> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/media', {
    method: 'POST',
    credentials: 'include',
    body: form,
  });
  if (!res.ok) return null;
  const body = (await res.json()) as { id: string };
  return body.id;
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
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollStartRef = useRef<number | null>(null);
  const lastIdRef = useRef<string | null>(null);

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

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    pollStartRef.current = null;
    setAwaitingAssistant(false);
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
          stopPolling();
          return true;
        }
      }
      if (pollStartRef.current && Date.now() - pollStartRef.current > POLL_CAP_MS) {
        stopPolling();
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

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const trimmed = text.trim();
    if (!trimmed && files.length === 0) {
      setError('Digite algo ou anexe uma imagem.');
      return;
    }
    setSending(true);
    try {
      const mediaIds: string[] = [];
      for (const file of files) {
        const id = await uploadMedia(file);
        if (!id) {
          setError(`Falha ao subir ${file.name}.`);
          setSending(false);
          return;
        }
        mediaIds.push(id);
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
        setSending(false);
        return;
      }
      setText('');
      setFiles([]);
      await loadInitial();
      startPolling();
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="mx-auto flex h-[calc(100vh-49px)] max-w-3xl flex-col gap-4 p-4">
      <div className="flex-1 space-y-3 overflow-y-auto rounded border border-slate-200 p-4 dark:border-slate-800">
        {messages.length === 0 && (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Nenhuma mensagem ainda. Envie algo abaixo — texto ou foto.
          </p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={
              m.role === 'user'
                ? 'ml-auto max-w-[80%] rounded-2xl bg-slate-900 px-3 py-2 text-sm text-white dark:bg-slate-100 dark:text-slate-900'
                : 'mr-auto max-w-[80%] rounded-2xl bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800'
            }
          >
            {m.content && <p className="whitespace-pre-wrap">{m.content}</p>}
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
        ))}
        {awaitingAssistant && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ex.: 150 g de arroz e 180 g de frango grelhado no almoço."
          rows={2}
          className="w-full resize-none rounded border border-slate-300 bg-white p-2 text-sm outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-900"
        />

        <div className="flex items-center gap-2 text-sm">
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            onChange={(e) => {
              const list = Array.from(e.target.files ?? []).slice(0, MAX_FILES);
              setFiles(list);
            }}
            className="text-xs"
          />
          {files.length > 0 && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {files.length} arquivo{files.length > 1 ? 's' : ''} selecionado{files.length > 1 ? 's' : ''}
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
