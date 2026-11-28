import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import type { ExtractionSummary } from '../api/extractions';
import { PipelineChanges } from './pipeline-changes';

const versions = {
  extraction_prompt_version: 'extract-3',
  extraction_contract_version: 'requirements-1',
  clarification_prompt_version: 'clarify-4',
  clarification_contract_version: 'clarification-1',
  clarification_review_prompt_version: 'clarify-review-1',
  conflict_assessment_prompt_version: 'conflict-assessment-1',
  structured_prompt_version: 'structured-2',
  extraction_context_contract_version: 'source-aliases-1',
};
const historical: ExtractionSummary = {
  id: '00000000-0000-4000-8000-000000000001',
  status: 'completed',
  progress: { completed_parts: 1, total_parts: 1 },
  error_code: null,
  created_at: '2026-11-28T12:00:00Z',
  model: 'test',
  version_ids: [],
  analysis_scope: '',
  configuration_current: false,
  pipeline_versions: { ...versions, clarification_prompt_version: 'clarify-3' },
  current_pipeline_versions: versions,
};

it('explains an old clarification version while retaining the historical result', () => {
  render(<PipelineChanges run={historical} />);
  expect(screen.getByText('Уточнения: clarify-3 → clarify-4')).toBeVisible();
  expect(screen.getByText(/Исторический результат/)).toBeVisible();
});
it('does not infer the current version for records without clarification metadata', () => {
  render(<PipelineChanges run={{ ...historical, pipeline_versions: null }} />);
  expect(screen.getByText('Уточнения: версия не зафиксирована → clarify-4')).toBeVisible();
});
it('does not label a current result historical', () => {
  const { container } = render(
    <PipelineChanges run={{ ...historical, configuration_current: true }} />,
  );
  expect(container).toBeEmptyDOMElement();
});
