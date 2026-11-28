import { expect, test } from '@playwright/test';
import {
  zClarificationView,
  zExtractionHistory,
  zExtractionSummary,
  zExtractionView,
} from '../src/shared/api/generated/zod.gen';
import {
  clarificationModelProfileFixture,
  fixtureHash,
  fixtureId,
  storedModelProfileFixture,
} from '../src/shared/api/test-network-fixtures';

const source = {
  file_id: fixtureId('layout-file'),
  version_id: fixtureId('immutable-version'),
  sha256: fixtureHash('source-hash'),
  fragment_id: fixtureId('source-fragment'),
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
const pipelineVersions = {
  clarification_contract_version: 'clarification-1',
  clarification_prompt_version: 'clarify-4',
  clarification_review_prompt_version: 'clarification-review-1',
  conflict_assessment_prompt_version: 'conflict-assessment-1',
  extraction_context_contract_version: 'source-aliases-1',
  extraction_contract_version: 'extraction-1',
  extraction_prompt_version: 'extract-4',
  structured_prompt_version: 'structured-3',
};
const run = zExtractionView.parse({
  id: fixtureId('layout-run'),
  status: 'failed',
  progress: { completed_parts: 4, total_parts: 4 },
  error_code: 'json_invalid',
  created_at: '2026-11-27T00:00:00Z',
  model: 'layout-readonly',
  version_ids: [source.version_id],
  analysis_scope: '',
  configuration_current: true,
  pipeline_versions: pipelineVersions,
  current_pipeline_versions: pipelineVersions,
  contract_version: pipelineVersions.extraction_contract_version,
  prompt_version: pipelineVersions.extraction_prompt_version,
  model_profile: { ...storedModelProfileFixture, model: 'layout-readonly' },
  coverage: { complete: true, total_fragments: 62, processed_fragments: 62, warnings: [] },
  requirements: Array.from({ length: 50 }, (_, index) => ({
    id: fixtureId(`layout-requirement-${index}`),
    category: 'functional',
    original_text: source.quote,
    normalized_text:
      'Продажи неизменяемы после передачи. Для восстановления требуются резервные копии сроком на 7 суток. После восстановления пользователь не должен видеть продажи вне текущего окна. '.repeat(
        3,
      ),
    sources: [source],
    status: 'needs_review',
  })),
});
const summary = zExtractionSummary.parse(run);
const history = zExtractionHistory.parse({ items: [summary], has_more: false });
const clarifications = zClarificationView.parse({
  run_id: run.id,
  history_id: fixtureId('layout-history'),
  cycle: 0,
  initialized: false,
  resume_pending: false,
  questions: [],
  decisions: [],
  risks: [],
  requirements: [],
  completed_cycles: [],
  conflict_assessments: [],
  metadata: {
    conflict_assessment_prompt_version: pipelineVersions.conflict_assessment_prompt_version,
    context_digest: fixtureHash('layout-context'),
    contract_version: pipelineVersions.clarification_contract_version,
    model_profile: { ...clarificationModelProfileFixture, name: 'layout-readonly' },
    prompt_version: pipelineVersions.clarification_prompt_version,
    review_prompt_version: pipelineVersions.clarification_review_prompt_version,
    review_start_requests: 0,
    coverage: {
      total_fragments: 62,
      reviewed_fragments: 0,
      total_history: 0,
      reviewed_history: 0,
      model_requests: 0,
      complete: false,
      unreviewed_fragment_ids: [source.fragment_id],
      unreviewed_question_ids: [],
    },
  },
});

test('a narrow results workspace keeps warning and tabs fixed while the table scrolls to source evidence', async ({
  page,
}, testInfo) => {
  const responses: Readonly<Record<string, unknown>> = {
    '/api/chats': [],
    '/api/model': { model: 'layout-readonly', available: true },
    '/api/preferences': { theme: 'light' },
    '/api/extractions/history': history,
    [`/api/extractions/${run.id}/status`]: summary,
    [`/api/extractions/${run.id}`]: run,
    [`/api/extractions/${run.id}/clarifications`]: clarifications,
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
  await page.goto(`/requirements?run=${run.id}`);
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
  const row = page.locator(`#requirement-${run.requirements[0]!.id}`);
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
    `/documents?version=${source.version_id}&fragment=${source.fragment_id}&run=${run.id}`,
  );
  await page.screenshot({ path: testInfo.outputPath('narrow-source-evidence.png') });
});
