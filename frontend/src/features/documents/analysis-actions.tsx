import { Link } from 'react-router';
import { extractionActive, type ExtractionSummary } from '../../shared/api/extractions';
import { Button } from '../../shared/ui/button';

export function AnalysisActions({
  previous,
  pending,
  failed,
  disabled,
}: {
  previous: ExtractionSummary | undefined;
  pending: boolean;
  failed: boolean;
  disabled: boolean;
}) {
  const active =
    previous !== undefined && (extractionActive(previous) || previous.status === 'waiting_input');
  let label = 'Извлечь требования';
  if (previous?.configuration_current) label = 'Повторить анализ';
  if (failed) label = 'Повторить запуск';
  if (pending) label = 'Запускаем…';
  return (
    <>
      {previous && <PreviousAnalysis run={previous} />}
      {!active && (
        <Button type="submit" variant={previous ? 'outline' : 'default'} disabled={disabled}>
          {label}
        </Button>
      )}
    </>
  );
}

function PreviousAnalysis({ run }: { run: ExtractionSummary }) {
  const active = extractionActive(run) || run.status === 'waiting_input';
  return (
    <div>
      <p className="notice">
        {run.status === 'waiting_input'
          ? 'Анализ ожидает ответа архитектора. Откройте вопросы, чтобы продолжить.'
          : active
            ? 'Эти документы уже анализируются.'
            : run.configuration_current
              ? 'Документы, область анализа и настройки не изменились.'
              : 'Настройки анализа изменились. Можно получить новый результат.'}
      </p>
      <Button asChild>
        <Link to={`/requirements?run=${encodeURIComponent(run.id)}`}>
          {active ? 'Открыть анализ' : 'Открыть результат'}
        </Link>
      </Button>
      {!active && run.configuration_current && (
        <p className="notice">
          Повторный анализ создаст отдельный результат и может дать другие формулировки. Предыдущий
          результат сохранится.
        </p>
      )}
    </div>
  );
}
