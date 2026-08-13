'use client';

/**
 * SP-118/SP-115 — renderiza o markdown gerado pelo `message_formatter` do
 * backend. Suporte mínimo, suficiente para o formato conhecido:
 *
 * - **bold** inline
 * - tabelas: sequência de linhas que começam por `|`, com uma linha divisora
 *   `| --- | --- |`. Linhas fora do bloco viram parágrafos.
 * - parágrafos separados por linhas em branco.
 *
 * Não temos dependência de biblioteca de markdown para manter o bundle
 * enxuto — o conteúdo é sempre gerado pelo nosso backend, então o dialeto
 * é controlado.
 */

import { JSX, useState } from 'react';
import { DiscardItemButton } from './DiscardItemButton';
import { LabelPhotoUploader } from './LabelPhotoUploader';
import { ManualCatalogForm } from './ManualCatalogForm';

type RecoveryItem = { id: string; name: string };

type Block =
  | { type: 'table'; rows: string[][] }
  | { type: 'paragraph'; text: string }
  | { type: 'recovery'; items: RecoveryItem[] };

// SP-140: marcador emitido pelo backend em `message_formatter._no_catalog_recovery_block`.
// Formato: `<!-- catalog-recovery: id1,id2,... -->`
const RECOVERY_MARKER = /^\s*<!--\s*catalog-recovery:\s*(.+?)\s*-->\s*$/;
// Extrai nomes em **bold** na ordem em que aparecem no bloco de recovery.
const BOLD_INLINE = /\*\*(.+?)\*\*/g;

function parseBlocks(content: string): Block[] {
  const lines = content.split('\n');
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === '') {
      i += 1;
      continue;
    }
    // SP-140: marcador de recovery — consome também as linhas seguintes
    // do bloco até a próxima linha em branco/tabela. Emite bloco custom
    // que vira botões clicáveis + texto explicativo.
    const recoveryMatch = RECOVERY_MARKER.exec(line);
    if (recoveryMatch) {
      const ids = recoveryMatch[1]
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      i += 1;
      const bodyLines: string[] = [];
      while (i < lines.length && lines[i].trim() !== '' && !lines[i].startsWith('|')) {
        bodyLines.push(lines[i]);
        i += 1;
      }
      // Extrai nomes em bold da 1ª linha ("Sem catálogo para: **X**, **Y**").
      const names: string[] = [];
      if (bodyLines.length > 0) {
        BOLD_INLINE.lastIndex = 0;
        let m: RegExpExecArray | null;
        while ((m = BOLD_INLINE.exec(bodyLines[0])) !== null) {
          names.push(m[1]);
        }
      }
      // Se casa em qtd com IDs + 1 → o primeiro bold é a label "Sem catálogo para".
      const nameCandidates = names.length === ids.length + 1 ? names.slice(1) : names;
      const items = ids.map((id, idx) => ({ id, name: nameCandidates[idx] ?? '' }));
      blocks.push({ type: 'recovery', items });
      continue;
    }
    // Início de tabela: linha começa com | e a próxima é divisor `| --- |`.
    if (line.startsWith('|') && i + 1 < lines.length && /^\|\s*-/.test(lines[i + 1])) {
      const rows: string[][] = [splitRow(line)];
      i += 2; // pula header + divisor
      while (i < lines.length && lines[i].startsWith('|')) {
        rows.push(splitRow(lines[i]));
        i += 1;
      }
      blocks.push({ type: 'table', rows });
      continue;
    }
    // Parágrafo: junta linhas consecutivas não vazias.
    const paraLines: string[] = [];
    while (i < lines.length && lines[i].trim() !== '' && !lines[i].startsWith('|')) {
      paraLines.push(lines[i]);
      i += 1;
    }
    blocks.push({ type: 'paragraph', text: paraLines.join('\n') });
  }
  return blocks;
}

function splitRow(line: string): string[] {
  return line
    .split('|')
    .slice(1, -1)
    .map((c) => c.trim());
}

function renderInline(text: string): JSX.Element[] {
  const parts: JSX.Element[] = [];
  const regex = /\*\*(.+?)\*\*/g;
  let lastIdx = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push(<span key={key++}>{text.slice(lastIdx, match.index)}</span>);
    }
    parts.push(<strong key={key++}>{match[1]}</strong>);
    lastIdx = match.index + match[0].length;
  }
  if (lastIdx < text.length) {
    parts.push(<span key={key++}>{text.slice(lastIdx)}</span>);
  }
  return parts;
}

function isApproxCell(text: string): boolean {
  return text.includes('≈');
}

function isPendingRowLabel(text: string): boolean {
  return text.endsWith('*');
}

export function AssistantContent({ content }: { content: string }) {
  const blocks = parseBlocks(content);
  const [openForm, setOpenForm] = useState<RecoveryItem | null>(null);
  const [openPhoto, setOpenPhoto] = useState<RecoveryItem | null>(null);
  const [discardedIds, setDiscardedIds] = useState<Set<string>>(new Set());

  return (
    <div className="space-y-3 text-sm">
      {blocks.map((block, idx) => {
        if (block.type === 'paragraph') {
          return (
            <p key={idx} className="whitespace-pre-wrap leading-relaxed">
              {renderInline(block.text)}
            </p>
          );
        }
        if (block.type === 'recovery') {
          const visibleItems = block.items.filter((it) => !discardedIds.has(it.id));
          if (visibleItems.length === 0) return null;
          return (
            <div
              key={idx}
              className="rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-900/20"
            >
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-200">
                Sem catálogo:
              </p>
              <ul className="space-y-3">
                {visibleItems.map((item) => (
                  <li key={item.id} className="space-y-1.5">
                    <span className="block font-medium">{item.name || 'item sem nome'}</span>
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        onClick={() => setOpenForm(item)}
                        className="rounded bg-slate-900 px-2 py-1 text-xs font-medium text-white transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
                      >
                        ✏️ Cadastrar manual
                      </button>
                      <button
                        type="button"
                        onClick={() => setOpenPhoto(item)}
                        className="rounded border border-slate-400 bg-white px-2 py-1 text-xs font-medium text-slate-800 transition hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
                      >
                        📸 Foto do rótulo
                      </button>
                      <DiscardItemButton
                        itemId={item.id}
                        itemName={item.name}
                        onDiscarded={() =>
                          setDiscardedIds((prev) => {
                            const next = new Set(prev);
                            next.add(item.id);
                            return next;
                          })
                        }
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          );
        }
        const [header, ...body] = block.rows;
        return (
          <div
            key={idx}
            className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
          >
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-100 dark:bg-slate-800">
                <tr>
                  {header.map((cell, i) => (
                    <th key={i} className="px-3 py-1.5 font-semibold">
                      {renderInline(cell)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.map((row, ri) => (
                  <tr
                    key={ri}
                    className="border-t border-slate-100 dark:border-slate-800"
                  >
                    {row.map((cell, ci) => {
                      const isLabel = ci === 0;
                      const pending = isLabel && isPendingRowLabel(cell);
                      const approx = !isLabel && isApproxCell(cell);
                      return (
                        <td
                          key={ci}
                          className={
                            'px-3 py-1.5 ' +
                            (pending
                              ? 'text-amber-700 dark:text-amber-400 '
                              : '') +
                            (approx ? 'italic ' : '') +
                            (isLabel ? 'text-slate-600 dark:text-slate-300' : 'font-medium')
                          }
                        >
                          {renderInline(cell)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
      {openForm && (
        <ManualCatalogForm
          promoteFoodItemId={openForm.id}
          suggestedName={openForm.name || undefined}
          onClose={() => setOpenForm(null)}
          onSuccess={() => {
            setOpenForm(null);
            // Força reload da página inteira do chat pra puxar o snapshot
            // atualizado (macros recomputadas). Alternativa cirúrgica seria
            // puxar o revalidate do DayTotalsBar por prop drilling —
            // deliberadamente evitando isso na v1 pra manter escopo.
            window.location.reload();
          }}
        />
      )}
      {openPhoto && (
        <LabelPhotoUploader
          promoteFoodItemId={openPhoto.id}
          itemName={openPhoto.name}
          onClose={() => setOpenPhoto(null)}
          onSent={() => setOpenPhoto(null)}
        />
      )}
    </div>
  );
}
