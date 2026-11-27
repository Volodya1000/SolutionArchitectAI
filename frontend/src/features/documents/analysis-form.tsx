import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { scopeKey } from '../../shared/api/client';
import {
  startExtraction,
  type Extraction,
  type ExtractionCommand,
} from '../../shared/api/extractions';
import { QueryError } from '../../shared/ui/query-error';
import { AnalysisActions } from './analysis-actions';
import { useAnalysisHistory } from './use-analysis-history';

export function AnalysisForm({ selected }: { selected: ReadonlySet<string> }) {
  const [scope, setScope] = useState('');
  const [pending, setPending] = useState<ExtractionCommand | null>(null);
  const navigate = useNavigate();
  const client = useQueryClient();
  const { history, previous } = useAnalysisHistory(selected, scope);
  const start = useMutation({
    mutationFn: startExtraction,
    onSuccess: async (run) => {
      client.setQueryData<Extraction[]>([...scopeKey, 'extractions'], (old = []) => [
        run,
        ...old.filter((item) => item.id !== run.id),
      ]);
      client.setQueryData([...scopeKey, 'extraction', run.id], run);
      await navigate(`/requirements?run=${encodeURIComponent(run.id)}`);
    },
  });
  function submit() {
    const versionIds = [...selected].sort();
    const command =
      pending &&
      pending.analysis_scope === scope.trim() &&
      pending.version_ids.join() === versionIds.join()
        ? pending
        : {
            operation_id: crypto.randomUUID(),
            version_ids: versionIds,
            analysis_scope: scope.trim(),
          };
    setPending(command);
    start.mutate(command);
  }
  return (
    <form
      className="analysis-form"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div>
        <h2>Анализ выбранных версий</h2>
        <p className="notice">Выбрано версий: {selected.size}.</p>
      </div>
      {selected.size === 0 && (
        <p className="notice">Выберите документы для анализа с помощью флажков в списке выше.</p>
      )}
      <details className="analysis-options">
        <summary>Уточнить анализ</summary>
        <p className="notice" id="analysis-scope-help">
          Это необязательное уточнение для модели. Обычный анализ можно запустить без него.
        </p>
        <label className="field-label" htmlFor="analysis-scope">
          На что обратить внимание (необязательно)
        </label>
        <textarea
          id="analysis-scope"
          aria-describedby="analysis-scope-help"
          value={scope}
          maxLength={1000}
          placeholder="Например: обратить особое внимание на безопасность и сроки хранения"
          onChange={(event) => setScope(event.target.value)}
          disabled={start.isPending}
        />
      </details>
      {selected.size > 20 && <p role="alert">Выберите не более 20 версий для одного анализа.</p>}
      <AnalysisActions
        previous={previous}
        pending={start.isPending}
        failed={start.isError}
        disabled={
          selected.size === 0 || selected.size > 20 || start.isPending || !history.isSuccess
        }
      />
      {selected.size > 0 && history.isError && (
        <QueryError
          error={history.error}
          retry={() => {
            void history.refetch();
          }}
        />
      )}
      {start.isError && (
        <p className="notice error-text" role="alert">
          {start.error.message} Повтор не создаст дубликат запуска.
        </p>
      )}
    </form>
  );
}
