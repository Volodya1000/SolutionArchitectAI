import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { expect, type Page } from '@playwright/test';
import { z } from 'zod';
import { clarificationSchema, type Question } from '../src/shared/api/clarifications';
import { versionSchema } from '../src/shared/api/documents';

export async function readClarifications(page: Page, run: string) {
  const response = await page.request.get(`/api/extractions/${run}/clarifications`);
  expect(response.ok()).toBe(true);
  const payload: unknown = await response.json();
  return clarificationSchema.parse(payload);
}

export async function runStatus(page: Page, run: string) {
  const response = await page.request.get(`/api/extractions/${run}`);
  const payload: unknown = await response.json();
  return z.object({ status: z.string(), requests: z.number() }).parse(payload);
}

export async function uploadAndAnalyze(page: Page, input: 'complete' | 'incomplete') {
  const buffer = await readFile(
    new URL(`../../docs/examples/pr3/reporting-system-${input}.md`, import.meta.url),
  );
  return uploadTextAndAnalyze(page, buffer);
}

export async function uploadTextAndAnalyze(page: Page, buffer: Buffer) {
  const name = `PR3-${crypto.randomUUID()}.md`;
  await page.goto('/documents');
  await page
    .getByLabel('Новый документ', { exact: true })
    .setInputFiles({ name, mimeType: 'text/markdown', buffer });
  const uploaded = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/documents' &&
      response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Загрузить документ', exact: true }).click();
  const payload: unknown = await (await uploaded).json();
  const version = versionSchema.parse(payload);
  const storageKey = z.object({ storage_key: z.string() }).parse(payload).storage_key;
  await page.getByRole('button', { name: `История версий ${name}` }).click();
  await page
    .getByRole('table', { name: `Версии ${name}` })
    .getByRole('checkbox')
    .first()
    .check();
  await page.getByLabel('Начать с новой историей уточнений', { exact: true }).check();
  await page.getByRole('button', { name: 'Извлечь требования', exact: true }).click();
  await expect(page).toHaveURL(/\/requirements\?run=/);
  const run = new URL(page.url()).searchParams.get('run');
  if (!run) throw new Error('An analysis must have a stable run ID');
  await expect
    .poll(async () => (await runStatus(page, run)).status, { timeout: 30000 })
    .toMatch(/^(waiting_input|completed)$/);
  return { run, version, name, storageKey };
}

export async function fillAnswer(
  page: Page,
  question: Question,
  text = 'Отклонять запрос и показывать допустимый диапазон дат',
) {
  if (new URL(page.url()).pathname === '/requirements') {
    await page.getByRole('tab', { name: /^Уточнения / }).click();
  }
  const card = page.getByRole('region', { name: question.text, exact: true }).first();
  await card.getByRole('textbox', { name: 'Ответ архитектора', exact: true }).fill(text);
  await card
    .getByRole('textbox', { name: 'Основание ответа', exact: true })
    .fill('Решение архитектора по результатам обсуждения');
  return card;
}

export function compose(...arguments_: string[]) {
  const project = process.env['SAA_QUALITY_PROJECT'];
  if (!project || !/^saa-quality-[a-z0-9-]+$/.test(project))
    throw new Error('Container faults require an isolated quality project');
  return execFileSync(
    'docker',
    [
      'compose',
      '--project-name',
      project,
      '--env-file',
      fileURLToPath(new URL('../../.env.quality', import.meta.url)),
      '--file',
      fileURLToPath(new URL('../../docker-compose.yml', import.meta.url)),
      ...arguments_,
    ],
    { encoding: 'utf8', timeout: 60000 },
  );
}

export async function restartWithVolumes(page: Page) {
  compose('restart', 'postgres');
  compose('restart', 'backend');
  await expect
    .poll(
      async () => {
        try {
          return (await page.request.get('/api/health/ready', { timeout: 2000 })).status();
        } catch {
          return 0;
        }
      },
      { timeout: 45000 },
    )
    .toBe(200);
}

export function removeSelectedTestSource(storageKey: string) {
  compose(
    'exec',
    '-T',
    'backend',
    'python',
    '-c',
    'import sys; from pathlib import Path; from solution_architect_ai.di.main import bootstrap; root=bootstrap().storage.root.resolve(); target=(root/sys.argv[1]).resolve(); assert target.is_relative_to(root); target.unlink()',
    storageKey,
  );
}
