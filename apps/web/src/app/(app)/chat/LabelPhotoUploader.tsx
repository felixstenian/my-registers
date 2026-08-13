'use client';

/**
 * SP-143 / T-B541 — modal do card recovery.
 *
 * Abre file picker embutido; ao "Enviar", faz upload de 1 imagem via
 * `POST /api/media` e envia `POST /chat/messages` com `media_ids` +
 * `promote_food_item_id`. O backend (`_handle_nutrition_label`)
 * detecta o metadata `promote_food_item_id` e acopla a promoção do
 * item legado ao fact recém-criado do rótulo.
 *
 * Falhas de upload viram inline error; falhas do POST /chat/messages
 * viram inline error também. Sucesso dispara reload da página (mesmo
 * padrão de `ManualCatalogForm.onSuccess`) pra puxar snapshot novo.
 */

import { ChangeEvent, useRef, useState } from 'react';
import { api } from '@/lib/api-client';

const ACCEPT_MIME = ['image/jpeg', 'image/png', 'image/webp'];
const ACCEPT_ATTR = 'image/png,image/jpeg,image/webp';
const MAX_FILE_BYTES = 8 * 1024 * 1024;

type Props = {
  promoteFoodItemId: string;
  itemName: string;
  onClose: () => void;
  onSent: () => void;
};

async function uploadMedia(file: File): Promise<{ ok: true; id: string } | { ok: false; reason: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/media', {
    method: 'POST',
    credentials: 'include',
    cache: 'no-store',
    body: form,
  });
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
  const reasons: Record<string, string> = {
    file_too_large: 'Arquivo maior que 8 MB.',
    invalid_image: 'Imagem inválida.',
    unsupported_media_type: 'Formato não suportado (use JPEG, PNG ou WEBP).',
    empty_upload: 'Arquivo vazio.',
  };
  return { ok: false, reason: reasons[code] ?? 'Falha no upload. Tente novamente.' };
}

export function LabelPhotoUploader({ promoteFoodItemId, itemName, onClose, onSent }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    setError(null);
    const picked = e.target.files?.[0] ?? null;
    if (!picked) {
      setFile(null);
      setPreviewUrl(null);
      return;
    }
    if (!ACCEPT_MIME.includes(picked.type)) {
      setError('Formato não suportado. Use JPEG, PNG ou WEBP.');
      return;
    }
    if (picked.size > MAX_FILE_BYTES) {
      setError('Arquivo maior que 8 MB. Reduza a qualidade ou tire outra foto.');
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(picked);
    setPreviewUrl(URL.createObjectURL(picked));
  }

  async function onSend() {
    if (!file) return;
    setSubmitting(true);
    setError(null);
    const uploaded = await uploadMedia(file);
    if (!uploaded.ok) {
      setError(uploaded.reason);
      setSubmitting(false);
      return;
    }
    const sent = await api<{ message_id: string }>('/chat/messages', {
      method: 'POST',
      body: JSON.stringify({
        text: null,
        media_ids: [uploaded.id],
        promote_food_item_id: promoteFoodItemId,
      }),
    });
    setSubmitting(false);
    if (!sent.ok) {
      setError(sent.error?.message ?? 'Falha ao enviar a mensagem.');
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    onSent();
    // Reload alinhado com o padrão de ManualCatalogForm — o snapshot
    // muda depois que o worker processa o rótulo, e o poll do page.tsx
    // não é acionado por envios feitos fora do composer.
    window.location.reload();
  }

  function onCancel() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Enviar foto do rótulo"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-4 shadow-xl dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">
            Foto do rótulo — {itemName || 'item'}
          </h2>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Fechar"
            className="text-slate-500 hover:text-slate-800 dark:hover:text-slate-100"
          >
            ×
          </button>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_ATTR}
          capture="environment"
          onChange={onFileChange}
          className="text-xs"
        />

        {previewUrl && (
          <img
            src={previewUrl}
            alt="Prévia do rótulo"
            className="mt-3 max-h-64 w-full rounded border border-slate-200 object-contain dark:border-slate-700"
          />
        )}

        {error && (
          <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
            {error}
          </p>
        )}

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onSend}
            disabled={!file || submitting}
            className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white transition disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900"
          >
            {submitting ? 'Enviando…' : 'Enviar'}
          </button>
        </div>
      </div>
    </div>
  );
}
