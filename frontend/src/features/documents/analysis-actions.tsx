import { Link } from 'react-router';
import { extractionActive, type Extraction } from '../../shared/api/extractions';
import { Button } from '../../shared/ui/button';

export function AnalysisActions({
  previous,
  pending,
  failed,
  disabled,
}: {
  previous: Extraction | undefined;
  pending: boolean;
  failed: boolean;
  disabled: boolean;
}) {
  const active = previous !== undefined && extractionActive(previous);
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

function PreviousAnalysis({ run }: { run: Extraction }) {
  const active = extractionActive(run);
  return (
    <div>
      <p className="notice">
        {active
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
