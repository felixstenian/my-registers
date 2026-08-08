# Especificações Técnicas — Composer do chat — UX (Bloco 1)

> **Rastreabilidade**: SP-15..SP-19 · Implementação: `apps/web/src/app/(app)/chat/page.tsx` (568 linhas) · `apps/web/src/lib/api-client.ts`.

## Escopo técnico

Componente client-side (`ChatPage`, `'use client'`) em Next.js 16 App Router. Gerencia estado de mensagens, texto, arquivos anexados, envio, polling de resposta, erros por arquivo, drag-and-drop, e modais (`CloseDayModal`, `PendingItemsModal`). Sem backend próprio — usa `POST /chat/messages` e `POST /media` da feature `chat-messaging` via proxy Next.js (`/api/*`).

## Interface

### Componente `ChatPage`

```tsx
export default function ChatPage() {
  // Estado
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const [awaitingAssistant, setAwaitingAssistant] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileErrors, setFileErrors] = useState<string[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);
  // ...modais, refs, polling
}
```

### Constantes

| Constante | Valor | Notas |
|---|---|---|
| `MAX_FILES` | 4 | SP-17 |
| `ACCEPT_MIME` | `['image/jpeg','image/png','image/webp']` | Deve refletir backend |
| `ACCEPT_ATTR` | `'image/png,image/jpeg,image/webp'` | Atributo `accept` do `<input>` |
| `MAX_FILE_BYTES` | `8 * 1024 * 1024` (8MB) | SP-18, idêntico ao backend |
| `POLL_INTERVAL_MS` | 1500 | Intervalo de polling |
| `POLL_CAP_MS` | 60000 | Timeout do polling |

### Funções de erro (SP-18)

```typescript
const UPLOAD_REASONS: Record<string, (name: string) => string> = {
  file_too_large: (name) => `\`${name}\` é maior que 8 MB e não pode ser enviada. Reduza a qualidade ou tire outra.`,
  invalid_image: (name) => `\`${name}\` não parece ser uma imagem válida.`,
  unsupported_media_type: (name) => `Formato de \`${name}\` não suportado. Envie JPEG, PNG ou WEBP.`,
  empty_upload: (name) => `\`${name}\` está vazia.`,
};
```

### Upload de mídia

```typescript
async function uploadMedia(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/media', {
    method: 'POST',
    credentials: 'include',
    cache: 'no-store',
    body: form,
  });
  // 201 → { ok: true, id }
  // erro → { ok: false, file, reason } (reason mapeado via UPLOAD_REASONS)
}
```

## Modelo de dados (client-side)

```typescript
type MediaRef = { id: string; content_type: string; url: string };
type Message = {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string | null;
  llm_intent: string | null;
  llm_confidence: number | null;
  media: MediaRef[];
  created_at: string;
  nutrient_fact_id?: string | null;  // SP-33
};
type UploadOk = { ok: true; id: string };
type UploadErr = { ok: false; file: string; reason: string };
```

## Fluxo de dados

### Envio de mensagem (SP-15)

1. Usuário digita na textarea e/ou anexa arquivos (input file SP-16 ou drag-and-drop SP-19).
2. **Enter** (sem Shift, sem `isComposing`, sem `sending`, com texto ou mídia) → `performSend()`.
3. **Shift+Enter** → quebra de linha (comportamento nativo).
4. `performSend`:
   a. Valida: se vazio (sem texto e sem mídia) → `setError('Digite algo ou anexe uma imagem.')`.
   b. `setSending(true)` — bloqueia novo envio.
   c. Para cada arquivo: `uploadMedia(file)` → `mediaIds` ou `uploadErrs`.
   d. Se `uploadErrs` → `setFileErrors` (não aborta o batch).
   e. Se `mediaIds.length === 0 && !trimmed` → aborta (nada válido).
   f. `POST /chat/messages { text, media_ids }` → `{ message_id }`.
   g. Limpa `text`, `files`, `fileInputRef`.
   h. `loadInitial()` + `startPolling()`.
5. `finally: setSending(false)`.

### Anexar arquivos (SP-16/SP-17/SP-18/SP-19)

`mergeFiles(incoming: File[], mode: 'replace' | 'append')`:
- `mode='replace'`: nova seleção via `<input>` substitui pré-anexados.
- `mode='append'`: drag-and-drop acumula.
- Para cada arquivo:
  - MIME fora de `ACCEPT_MIME` → `rejectedByMime` → erro SP-18.
  - `file.size > MAX_FILE_BYTES` → `rejectedBySize` → erro SP-18.
  - Senão → `allowed`.
- Cap de 4: `overflow = max(0, total - MAX_FILES)`; excedentes → erro com nome.
- `setFiles([...base, ...acceptedFromIncoming])`.

### Drag-and-drop (SP-19)

- `onDragEnter`: se `dataTransfer.types` inclui `Files` → `dragCounterRef++`, `setIsDragging(true)`.
- `onDragOver`: `preventDefault()` (necessário para permitir drop).
- `onDragLeave`: `dragCounterRef--`; se 0 → `setIsDragging(false)`.
- `onDrop`: `dragCounterRef=0`, `setIsDragging(false)`, `mergeFiles(files, 'append')`.
- `dragCounterRef` evita flicker ao passar por elementos filhos.

### Polling de resposta

`startPolling()`:
- `pollStartRef = Date.now()`, `setAwaitingAssistant(true)`.
- `tick()`: `GET /chat/messages?after={lastId}`.
  - Se mensagens novas e alguma `role='assistant'` → `setTotalsRevalidateKey++` (SP-116), `stopPolling()`.
  - Se `Date.now() - pollStartRef > POLL_CAP_MS` → `stopPolling('timeout')`.
- Poll imediato (não espera 1500ms no primeiro tick); depois `setInterval(tick, 1500)`.

## Regras de negócio

1. **Enter envia, Shift+Enter quebra linha** (SP-15): `event.key === 'Enter'` + `!event.shiftKey` + `!event.nativeEvent.isComposing` + `!sending` + `canSend`.
2. **Cap de 4 anexos** (SP-17): excedentes listados por nome; contagem inclui pré-anexados.
3. **Allowlist MIME** (SP-18): `ACCEPT_MIME` reflete backend; rejeitados têm mensagem com nome.
4. **Cap de 8MB client-side** (SP-18): `MAX_FILE_BYTES` bloqueia antes do upload para feedback imediato.
5. **Não aborta batch por 1 falha** (SP-18): válidos são anexados; `uploadErrs` separado.
6. **Compositor não perde texto** (SP-18): `setText('')` só roda após `POST /chat/messages` sucesso.
7. **`capture="environment"`** (SP-16): dica para câmera traseira em mobile; ignorada em desktop.
8. **Anti-duplo-envio**: `sending` state; Enter ignorado enquanto `true`.
9. **IME**: `isComposing` respeitado (chinês/japonês/coreano).

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | URL base da API (relativo `/api`, browser-only) | `/api` | Sim |

Sem variáveis específicas do composer — tudo hardcoded ou via `api-client.ts`.

## Referências de implementação

- **Componente principal**: `apps/web/src/app/(app)/chat/page.tsx` — `ChatPage`, `performSend`, `mergeFiles`, `onTextareaKeyDown`, drag handlers, `uploadMedia`, `UPLOAD_REASONS`, `TypingIndicator`.
- **API client**: `apps/web/src/lib/api-client.ts` — wrapper `api<T>(path, options)`.
- **Subcomponentes**: `AssistantContent.tsx` (SP-115..118), `DayTotalsBar.tsx` (SP-116), `PendingItemsModal.tsx` (SP-117), `CloseDayModal.tsx` (T-704).
- **Proxy**: `apps/web/proxy.ts` — protege `/api/*` por presença de cookie.
- **Tests**: [Implementação não localizada] — não há testes E2E dedicados ao composer no repo; coverage via testes manuais. <!-- TODO: verificar se há playwright/cypress tests -->
