import { useMutation, useQueryClient } from '@tanstack/react-query';
import { scopeKey } from '../../shared/api/client';
import { cancelExtraction, extractionActive, type Extraction } from '../../shared/api/extractions';
import { errorText } from '../../shared/api/resource-client';
import { Button } from '../../shared/ui/button';

const statusText: Readonly<Record<Extraction['status'], string>> = {
  queued: 'Извлечение в очереди',
  running: 'Выполняется извлечение…',
  cancelling: 'Останавливаем извлечение…',
  completed: 'Извлечение завершено',
  failed: 'Извлечение завершилось ошибкой',
  cancelled: 'Извлечение отменено',
};

export function RunStatus({ run }: { run: Extraction }) {
  const client = useQueryClient();
  const cancel = useMutation({
    mutationFn: () => cancelExtraction(run.id),
    onSuccess: (updated) => {
      client.setQueryData([...scopeKey, 'extraction', run.id], updated);
      client.setQueryData<Extraction[]>([...scopeKey, 'extractions'], (old = []) =>
        old.map((item) => (item.id === updated.id ? updated : item)),
      );
    },
  });
  return (
    <section className="extraction-status" aria-label="Состояние извлечения">
      <div className="section-heading">
        <strong role="status">{statusText[run.status]}</strong>
        {extractionActive(run) && (
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
      <p className={run.coverage.complete ? 'notice' : 'notice evidence-warning'}>
        {run.coverage.complete
          ? 'Весь текст документа обработан.'
          : `Неполное покрытие: ${run.coverage.processed_fragments} из ${run.coverage.total_fragments} фрагментов. Результат может содержать пропуски.`}
      </p>
      {(run.coverage.warnings ?? []).map((warning) => (
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
      {cancel.isError && (
        <p className="notice error-text" role="alert">
          {cancel.error.message}
        </p>
      )}
    </section>
  );
}
