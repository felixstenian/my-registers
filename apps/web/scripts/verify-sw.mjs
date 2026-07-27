#!/usr/bin/env node
// T-B409 — Sanity check pós-build do service worker.
//
// Garante INV-11 (SW nunca cacheia /api/*) e SP-130 (estratégias
// principais presentes) via análise estática do bundle gerado.
//
// Não substitui teste comportamental (que precisaria vitest + jsdom),
// mas pega regressões óbvias — ex.: alguém trocou NetworkOnly por
// StaleWhileRevalidate no matcher da API sem perceber.

import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import process from 'node:process';

const SW_SRC = resolve('src/app/sw.ts');
const SW_BUNDLE = resolve('public/sw.js');

if (!existsSync(SW_SRC)) {
  console.error(`FAIL: ${SW_SRC} não existe.`);
  process.exit(1);
}

const source = readFileSync(SW_SRC, 'utf8');

// O bundle é opcional (só existe pós-build). Sanity check adicional
// quando presente: confirmar que ao menos o path /api/ e /offline
// aparecem no output (minified names para as classes fogem do regex).
const bundle = existsSync(SW_BUNDLE) ? readFileSync(SW_BUNDLE, 'utf8') : null;

const checks = [
  {
    name: 'INV-11 — matcher /api/ presente em sw.ts',
    ok: /\/\^https\?:\\\/\\\/\[\^\/\]\+\\\/api\\\//.test(source) ||
        /\/api\\?\//.test(source),
    hint: 'sw.ts deve ter um runtimeCaching com matcher para /api/.',
  },
  {
    name: 'INV-11 — NetworkOnly usado como handler de /api/',
    ok: /\/api[^}]*handler:\s*new NetworkOnly/s.test(source),
    hint: 'A regra do /api/ precisa usar `new NetworkOnly()` em sw.ts.',
  },
  {
    name: 'SP-135 — fallback /offline em sw.ts',
    ok: /url:\s*['"]\/offline['"]/.test(source),
    hint: 'sw.ts precisa declarar fallback para "/offline" em `fallbacks.entries`.',
  },
  {
    name: 'SP-132 — listener de SKIP_WAITING em sw.ts',
    ok: /SKIP_WAITING/.test(source) && /skipWaiting/.test(source),
    hint: 'sw.ts precisa escutar message SKIP_WAITING chamando skipWaiting().',
  },
  {
    name: '(pós-build) bundle contém /api/ e /offline',
    ok: !bundle || (/\/api\b/.test(bundle) && /\/offline/.test(bundle)),
    hint: 'Bundle sw.js gerado não referencia /api ou /offline — algo mudou no Serwist.',
    optional: !bundle,
  },
];

let failed = 0;
for (const { name, ok, hint, optional } of checks) {
  if (ok) {
    console.log(`OK   ${name}${optional ? ' (pulado — bundle ausente)' : ''}`);
  } else {
    console.error(`FAIL ${name}\n     ${hint}`);
    failed++;
  }
}

if (failed > 0) {
  console.error(`\n${failed} check(s) falharam.`);
  process.exit(1);
}
console.log('\nTodos os checks passaram.');
