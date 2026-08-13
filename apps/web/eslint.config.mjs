// Flat config ESLint (Next.js 16 removeu `next lint`; FE-05).
//
// `eslint-config-next` 16.x já exporta um array de Linter.Config (flat) que
// bundula typescript-eslint + plugins de React/JSX-a11y/import/Next. Basta
// espalhar e complementar ignores/rules específicas deste projeto.

import nextConfig from 'eslint-config-next';

const eslintConfig = [
  ...nextConfig,
  {
    // nextConfig já ignora .next/**, out/**, build/** e next-env.d.ts.
    //
    // `e2e/` é código Playwright, não React: fixtures usam o parâmetro `use`
    // do Playwright (`await use(...)`) que o eslint-plugin-react-hooks confunde
    // com a Hook API do React (react-hooks/rules-of-hooks). Lint de testes
    // E2E é responsabilidade do @playwright/test, não do ESLint app.
    //
    // `playwright-report/` e `test-results/` são artefatos de run local
    // (gitignored) — ignorados pra não poluir a máquina do dev.
    ignores: ['e2e/**', 'playwright-report/**', 'test-results/**'],
  },
  {
    files: ['**/*.{ts,tsx}'],
    rules: {
      // Dívida técnica aprovada — ESLint baseline FE-05.
      //
      // `react-hooks/set-state-in-effect` é rule nova do
      // eslint-plugin-react-hooks v7 (ship do eslint-config-next 16) que não
      // existia quando `next lint` era usado. Ela flagra os padrões de
      // data-fetch-on-mount deste codebase (InstallButton, DayTotalsBar e
      // chat/page.tsx) — exatamente o escopo de refator de FE-01 (api-client
      // hardening + estados de erro), FE-09 (error.tsx no (app)) e FE-16
      // (extrair hooks do chat/page). Resolver aqui seria refactor
      // comportamental fora do escopo de FE-05 (restaurar o baseline de lint,
      // não mudar padrões). Reativar quando FE-01/FE-09/FE-16 fecharem.
      'react-hooks/set-state-in-effect': 'off',
    },
  },
];

export default eslintConfig;