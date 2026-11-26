import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { scopeKey } from '../../shared/api/client';
import {
  startExtraction,
  type Extraction,
  type ExtractionCommand,
} from '../../shared/api/extractions';
import { Button } from '../../shared/ui/button';

export function AnalysisForm({ selected }: { selected: ReadonlySet<string> }) {
  const [scope, setScope] = useState('');
  const [pending, setPending] = useState<ExtractionCommand | null>(null);
  const navigate = useNavigate();
  const client = useQueryClient();
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
        <p className="notice">
          Выбрано версий: {selected.size}. Извлечённые кандидаты сохраняются отдельно от чата.
        </p>
      </div>
      <label htmlFor="analysis-scope">Область анализа</label>
      <textarea
        id="analysis-scope"
        value={scope}
        maxLength={1000}
        placeholder="Например, требования к сервису отчётности"
        onChange={(event) => setScope(event.target.value)}
        disabled={start.isPending}
      />
      {selected.size > 20 && <p role="alert">Выберите не более 20 версий для одного анализа.</p>}
      <Button type="submit" disabled={selected.size === 0 || selected.size > 20 || start.isPending}>
        {start.isPending ? 'Запускаем…' : start.isError ? 'Повторить запуск' : 'Извлечь требования'}
      </Button>
      {start.isError && (
        <p className="notice error-text" role="alert">
          {start.error.message} Повтор использует тот же идентификатор операции.
        </p>
      )}
    </form>
  );
}
