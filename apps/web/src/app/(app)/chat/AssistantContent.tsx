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

import { JSX } from 'react';

type Block =
  | { type: 'table'; rows: string[][] }
  | { type: 'paragraph'; text: string };

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
    </div>
  );
}
