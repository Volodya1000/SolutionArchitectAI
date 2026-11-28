import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  cancelExtraction,
  extractionActive,
  type Extraction,
  type ExtractionSummary,
} from '../../shared/api/extractions';
import { recordExtraction } from '../../shared/api/use-extraction-history';
import { errorText } from '../../shared/api/resource-client';
import { Button } from '../../shared/ui/button';
import { PipelineChanges } from '../../shared/ui/pipeline-changes';

const statusText: Readonly<Record<Extraction['status'], string>> = {
  queued: 'Извлечение в очереди',
  running: 'Выполняется извлечение…',
  waiting_input: 'Ожидает ответа архитектора',
  cancelling: 'Останавливаем извлечение…',
  completed: 'Извлечение завершено',
  failed: 'Извлечение завершилось ошибкой',
  cancelled: 'Извлечение отменено',
};

export function RunStatus({
  run,
  coverage,
}: {
  run: ExtractionSummary;
  coverage: Extraction['coverage'] | undefined;
}) {
  const client = useQueryClient();
  const cancel = useMutation({
    retry: false,
    mutationFn: () => cancelExtraction(run.id),
    onSuccess: (updated) => {
      recordExtraction(client, updated);
    },
  });
  return (
    <section className="surface-card extraction-status" aria-label="Состояние извлечения">
      <div className="section-heading">
        <strong role="status">{statusText[run.status]}</strong>
        {canCancel(run) && (
          <Button
            variant="outline"
            disabled={cancel.isPending || run.status === 'cancelling'}
            onClick={() => cancel.mutate()}
          >
            Отменить извлечение
          </Button>
        )}
      </div>
      <p>
        Обработано частей: {run.progress.completed_parts} из {run.progress.total_parts}
      </p>
      <progress
        aria-label="Прогресс извлечения"
        value={run.progress.completed_parts}
        max={Math.max(run.progress.total_parts, 1)}
      />
      {coverage && (
        <p className={coverage.complete ? 'notice' : 'notice evidence-warning'}>
          {coverage.complete
            ? 'Весь текст документа обработан.'
            : `Неполное покрытие: ${coverage.processed_fragments} из ${coverage.total_fragments} фрагментов. Результат может содержать пропуски.`}
        </p>
      )}
      {(coverage?.warnings ?? []).map((warning) => (
        <p className="notice evidence-warning" key={warning}>
          {warning === 'cross_part_semantic_review_required'
            ? 'Противоречия между частями документа не проверены.'
            : `Ограничение обработки источника: ${warning}`}
        </p>
      ))}
      <p className="notice">
        Модель: {run.model} · {new Date(run.created_at).toLocaleString('ru-RU')}
      </p>
      {run.error_code && (
        <p className="notice error-text" role="alert">
          {errorText(run.error_code)}
        </p>
      )}
      <PipelineChanges run={run} />
      {cancel.isError && (
        <p className="notice error-text" role="alert">
          {cancel.error.message}
        </p>
      )}
    </section>
  );
}

function canCancel(run: ExtractionSummary): boolean {
  return extractionActive(run) || run.status === 'waiting_input';
}
