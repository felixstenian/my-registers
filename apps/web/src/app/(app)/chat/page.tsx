export default function ChatPage() {
  return (
    <main className="mx-auto flex min-h-full max-w-2xl flex-col gap-4 p-8">
      <h1 className="text-2xl font-semibold">Chat</h1>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Fase 1 concluída: autenticação ativa. O chat real com a LLM entra na Fase 2
        (mensagens + upload) e na Fase 3 (integração Anthropic).
      </p>
      <footer className="mt-auto pt-6 text-xs text-slate-500 dark:text-slate-400">
        As estimativas nutricionais desta ferramenta são aproximações e não substituem
        acompanhamento médico ou nutricional.
      </footer>
    </main>
  );
}
