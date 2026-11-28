import assert from 'node:assert/strict';
import { access, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { ESLint } from 'eslint';
import ts from 'typescript';

const root = process.cwd();
const files = new Set();
const eslint = new ESLint();
async function create(relative, source) {
  const file = path.join(root, relative);
  await assert.rejects(access(file), `Probe would overwrite ${relative}`);
  await writeFile(file, source);
  files.add(file);
  return file;
}
async function lint(relative, source, expected) {
  const file = await create(relative, source);
  const results = await eslint.lintFiles([file]);
  const rules = results.flatMap((result) => result.messages.map((message) => message.ruleId));
  if (expected)
    assert.ok(rules.includes(expected), `${relative}: expected ${expected}; got ${rules}`);
  else {
    assert.ok(!rules.includes('boundaries/dependencies'), `${relative}: legal import rejected`);
    assert.ok(!rules.includes('no-restricted-imports'), `${relative}: legal test imports rejected`);
  }
}
try {
  await lint(
    'src/shared/ui/test-import-probe.ts',
    "export { fixtureId } from '../api/test-network-fixtures';",
    'no-restricted-imports',
  );
  await lint(
    'src/shared/ui/pytest-import-probe.ts',
    "export { expect } from 'vitest';",
    'no-restricted-imports',
  );
  await lint(
    'src/shared/api/allowed-probe.test.ts',
    "import { it, expect } from 'vitest'; it('works', () => { expect(true).toBe(true); });",
    null,
  );
  await lint(
    'src/shared/api/expect-probe.test.ts',
    "import { it, expect } from 'vitest'; it('works', () => { expect(true); });",
    'vitest/valid-expect',
  );
  await lint(
    'src/shared/api/focus-probe.test.ts',
    "import { it, expect } from 'vitest'; it.only('works', () => { expect(true).toBe(true); });",
    'vitest/no-focused-tests',
  );
  await lint(
    'src/shared/api/effects-probe.test.tsx',
    "import { it } from 'vitest'; import { fireEvent, screen, waitFor } from '@testing-library/react'; it('works', async () => { await waitFor(() => fireEvent.click(screen.getByRole('button'))); });",
    'testing-library/no-wait-for-side-effects',
  );
  await lint(
    'src/shared/api/node-probe.test.tsx',
    "import { it } from 'vitest'; import { screen } from '@testing-library/react'; it('works', () => { screen.getByRole('button').parentElement; });",
    'testing-library/no-node-access',
  );
  await lint(
    'e2e/await-probe.spec.ts',
    "import { test } from '@playwright/test'; test('works', async ({page}) => { page.goto('/'); });",
    'playwright/missing-playwright-await',
  );
  await lint(
    'e2e/timeout-probe.spec.ts',
    "import { test } from '@playwright/test'; test('works', async ({page}) => { await page.waitForTimeout(100); });",
    'playwright/no-wait-for-timeout',
  );
  await lint(
    'e2e/focus-probe.spec.ts',
    "import { test } from '@playwright/test'; test.only('works', async ({page}) => { await page.goto('/'); });",
    'playwright/no-focused-test',
  );
  await lint('src/pages/allowed-probe.ts', "export { Button } from '../shared/ui/button';", null);
  await lint(
    'src/shared/ui/forbidden-probe.ts',
    "export { Chat } from '@/features/chat';",
    'boundaries/dependencies',
  );
  await lint(
    'src/shared/ui/complex-probe.ts',
    `export function probe(x: number) { ${Array.from({ length: 11 }, (_, i) => `if(x===${i}) return ${i};`).join('')} return 99; }`,
    'complexity',
  );
  await lint(
    'src/shared/ui/depth-probe.ts',
    'export function probe(x: number) { if(x>0){if(x>1){if(x>2){if(x>3){return x;}}}}return 0;}',
    'max-depth',
  );
  await create(
    'src/shared/ui/cycle-b-probe.ts',
    "import { a } from './cycle-a-probe'; export const b = () => a();",
  );
  await lint(
    'src/shared/ui/cycle-a-probe.ts',
    "import { b } from './cycle-b-probe'; export const a = () => b();",
    'import-x/no-cycle',
  );
  const probes = [
    ['unchecked', 'export const value: number = [1][99];'],
    ['optional', 'export const value: { x?: number } = { x: undefined };'],
    ['strict', 'export function probe(value) { return value; }'],
    ['override', 'class Base { value() {} } export class Child extends Base { value() {} }'],
    [
      'fallthrough',
      'export function probe(x: number) { switch(x) { case 0: x++; case 1: return x; } }',
    ],
  ];
  for (const [name, source] of probes) await create(`src/shared/ui/${name}-type-probe.ts`, source);
  const config = ts.readConfigFile(path.join(root, 'tsconfig.json'), ts.sys.readFile);
  assert.ok(!config.error);
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, root);
  const program = ts.createProgram(parsed.fileNames, parsed.options);
  const diagnostics = ts.getPreEmitDiagnostics(program);
  for (const [name] of probes)
    assert.ok(
      diagnostics.some((item) => item.file?.fileName.endsWith(`${name}-type-probe.ts`)),
      `TypeScript did not reject ${name}`,
    );
  process.stdout.write(
    'Architecture, aliases, cycles, complexity/depth and strict TypeScript probes passed.\n',
  );
} finally {
  for (const file of files) await unlink(file);
}
