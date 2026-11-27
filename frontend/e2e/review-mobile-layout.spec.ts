import { expect, test } from '@playwright/test';

const source = {
  file_id: 'layout-file',
  version_id: 'immutable-version',
  sha256: 'source-hash',
  fragment_id: 'source-fragment',
  locator: {
    kind: 'lines',
    start: 28,
    end: 28,
    section: 'Требования к сохранности и восстановлению финансовых отчётов',
  },
  quote: 'После восстановления пользователь не должен видеть продажи вне текущего окна.',
  status: 'verified',
  reason: null,
};
const run = {
  id: 'layout-run',
  status: 'failed',
  progress: { completed_parts: 4, total_parts: 4 },
  error_code: 'json_invalid',
  created_at: '2026-11-27T00:00:00Z',
  model: 'layout-readonly',
  version_ids: ['immutable-version'],
  analysis_scope: '',
  configuration_current: true,
  coverage: { complete: true, total_fragments: 62, processed_fragments: 62 },
  requirements: Array.from({ length: 50 }, (_, index) => ({
    id: `layout-requirement-${index}`,
    category: 'functional',
    original_text: source.quote,
    normalized_text:
      'Продажи неизменяемы после передачи. Для восстановления требуются резервные копии сроком на 7 суток. После восстановления пользователь не должен видеть продажи вне текущего окна. '.repeat(
        3,
      ),
    sources: [source],
    status: 'needs_review',
  })),
};
const clarifications = {
  run_id: run.id,
  history_id: 'layout-history',
  cycle: 0,
  initialized: false,
  resume_pending: false,
  questions: [],
  decisions: [],
  risks: [],
  requirements: [],
  completed_cycles: [],
  metadata: {
    coverage: {
      total_fragments: 62,
      reviewed_fragments: 0,
      total_history: 0,
      reviewed_history: 0,
      model_requests: 0,
      complete: false,
      unreviewed_fragment_ids: ['source-fragment'],
      unreviewed_question_ids: [],
    },
  },
};

test('a narrow results workspace keeps warning and tabs fixed while the table scrolls to source evidence', async ({
  page,
}, testInfo) => {
  const responses: Readonly<Record<string, unknown>> = {
    '/api/chats': [],
    '/api/model': { model: 'layout-readonly', available: true },
    '/api/preferences': { theme: 'light' },
    '/api/extractions/history': { items: [run], has_more: false },
    '/api/extractions/layout-run/status': run,
    '/api/extractions/layout-run': run,
    '/api/extractions/layout-run/clarifications': clarifications,
  };
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    async (route) => {
      const request = route.request();
      expect(request.method()).toBe('GET');
      const payload = responses[new URL(request.url()).pathname];
      expect(payload).toBeDefined();
      await route.fulfill({ json: payload });
    },
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/requirements?run=layout-run');
  const table = page.getByRole('table', { name: 'Кандидаты требований' });
  await expect(table).toBeVisible();
  const workspace = page.locator('.workspace-content');
  expect(await workspace.evaluate((element) => element.scrollWidth)).toBeLessThanOrEqual(
    await workspace.evaluate((element) => element.clientWidth),
  );
  const warning = page.getByRole('alert').filter({ hasText: 'Проверка уточнений не завершена' });
  await expect(warning).toContainText('проверено 0 из 62 фрагментов');
  const tabs = page.getByRole('tablist', { name: 'Результаты анализа' });
  await tabs.scrollIntoViewIfNeeded();
  const row = page.locator('#requirement-layout-requirement-0');
  const sourceLink = row.getByRole('link', { name: /^Источник/ });
  await row.getByRole('button', { name: 'Обсудить', exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect(sourceLink).toBeFocused();
  const tableScroll = page.locator('.table-scroll');
  expect(await tableScroll.evaluate((element) => element.scrollWidth)).toBeGreaterThan(
    await tableScroll.evaluate((element) => element.clientWidth),
  );
  expect(await tableScroll.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
  expect(await workspace.evaluate((element) => element.scrollLeft)).toBe(0);
  for (const element of [warning, tabs, ...(await tabs.getByRole('tab').all()), sourceLink]) {
    const bounds = await element.boundingBox();
    if (!bounds) throw new Error('Expected the result element bounds');
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
  }
  await expect(sourceLink).toHaveAttribute(
    'href',
    '/documents?version=immutable-version&fragment=source-fragment&run=layout-run',
  );
  await page.screenshot({ path: testInfo.outputPath('narrow-source-evidence.png') });
});
