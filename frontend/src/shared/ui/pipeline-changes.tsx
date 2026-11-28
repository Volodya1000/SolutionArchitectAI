import type { ExtractionSummary } from '../api/extractions';

type Versions = NonNullable<ExtractionSummary['pipeline_versions']>;
const labels: Record<keyof Versions, string> = {
  extraction_prompt_version: 'Извлечение',
  extraction_contract_version: 'Контракт извлечения',
  clarification_prompt_version: 'Уточнения',
  clarification_contract_version: 'Контракт уточнений',
  clarification_review_prompt_version: 'Перепроверка источников',
  conflict_assessment_prompt_version: 'Проверка противоречий',
  structured_prompt_version: 'Структурированный ответ',
  extraction_context_contract_version: 'Подготовка источников',
};

export function PipelineChanges({ run }: { run: ExtractionSummary }) {
  if (run.configuration_current || !run.current_pipeline_versions) return null;
  const current = run.current_pipeline_versions;
  const changes = (Object.keys(labels) as (keyof Versions)[]).filter(
    (key) => run.pipeline_versions?.[key] !== current[key],
  );
  return (
    <div className="notice">
      <p>Исторический результат. Исходники и прежний результат сохранены.</p>
      {changes.map((key) => (
        <p key={key}>
          {labels[key]}: {run.pipeline_versions?.[key] ?? 'версия не зафиксирована'} →{' '}
          {current[key] ?? 'версия не зафиксирована'}
        </p>
      ))}
    </div>
  );
}
