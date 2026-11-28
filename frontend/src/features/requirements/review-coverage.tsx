import { extractionActive, type ExtractionSummary } from '../../shared/api/extractions';
import { useClarifications } from '../../shared/api/use-clarifications';

export function ReviewCoverage({ run }: { run: ExtractionSummary }) {
  const query = useClarifications(run.id);
  const coverage = query.data?.metadata?.coverage;
  if (!coverage || coverage.complete) return null;
  const active = extractionActive(run);
  return (
    <p className={active ? 'notice' : 'notice evidence-warning'} role={active ? 'status' : 'alert'}>
      {active ? 'Проверяем уточнения' : 'Проверка уточнений не завершена'}: проверено{' '}
      {coverage.reviewed_fragments} из {coverage.total_fragments} фрагментов,{' '}
      {coverage.reviewed_history} из {coverage.total_history} ответов
      {active ? '.' : '; отсутствие вопроса не означает полноту.'}
    </p>
  );
}
