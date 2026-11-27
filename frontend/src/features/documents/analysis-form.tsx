import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import { recordExtraction } from '../../shared/api/use-extraction-history';
import { QueryError } from '../../shared/ui/query-error';
import { AnalysisActions } from './analysis-actions';
import { useAnalysisHistory } from './use-analysis-history';
import { useAnalysisCommand } from './use-analysis-command';
import { AnalysisContextStatus } from './analysis-context';
import { useAnalysisContext } from './use-analysis-context';

type AnalysisState = ReturnType<typeof useAnalysisCommand>;
type AnalysisHistory = ReturnType<typeof useAnalysisHistory>;

export function AnalysisForm({
  selected,
  scope,
  setScope,
}: {
  selected: ReadonlySet<string>;
  scope: string;
  setScope: (scope: string) => void;
}) {
  const [newHistory, setNewHistory] = useState(false);
  const context = useAnalysisContext(newHistory);
  const historyId = context.historyId;
  const navigate = useNavigate();
  const client = useQueryClient();
  const { history, previous } = useAnalysisHistory(selected, scope, newHistory, historyId);
  const state = useAnalysisCommand(async (run) => {
    recordExtraction(client, run);
    await navigate(`/requirements?run=${encodeURIComponent(run.id)}`);
  });
  const { pending, recovery, start, submit } = state;
  return (
    <form
      className="surface-card analysis-form"
      onSubmit={(event) => {
        event.preventDefault();
        submit(selected, scope, newHistory, historyId);
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
          disabled={start.isPending || (pending !== null && !recovery.data)}
        />
      </details>
      {selected.size > 20 && <p role="alert">Выберите не более 20 версий для одного анализа.</p>}
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={newHistory}
          onChange={(event) => setNewHistory(event.target.checked)}
          disabled={start.isPending || pending !== null}
        />
        Начать с новой историей уточнений
      </label>
      <AnalysisContextStatus context={context} newHistory={newHistory} />
      <AnalysisRecovery state={state} />
      <AnalysisCommandActions
        state={state}
        historyState={{ history, previous }}
        selectedCount={context.ready ? selected.size : 0}
      />
      <AnalysisErrors state={state} history={history} />
    </form>
  );
}

function AnalysisRecovery({ state }: { state: AnalysisState }) {
  const { pending, recovery } = state;
  const recovering = pending !== null && recovery.isPending;
  return (
    <>
      {recovery.data && (
        <p className="notice">
          <Link
            className="text-link"
            to={`/requirements?run=${encodeURIComponent(recovery.data.id)}`}
          >
            Открыть восстановленный анализ
          </Link>
        </p>
      )}
      {recovering && <p role="status">Проверяем результат предыдущего запуска…</p>}
      {pending && !recovering && !recovery.data && (
        <p className="notice">
          Повторяем сохранённую команду независимо от текущего выбора. Версий:{' '}
          {pending.version_ids.length}. Уточнение: {pending.analysis_scope || 'Без уточнения'}.
        </p>
      )}
    </>
  );
}

function AnalysisCommandActions({
  state,
  historyState,
  selectedCount,
}: {
  state: AnalysisState;
  historyState: AnalysisHistory;
  selectedCount: number;
}) {
  const { pending, recovery, start } = state;
  const { history, previous } = historyState;
  if (pending && !recovery.data) return <PendingAnalysisActions state={state} />;
  return (
    <AnalysisActions
      previous={previous}
      pending={start.isPending}
      failed={start.isError}
      disabled={
        selectedCount === 0 ||
        selectedCount > 20 ||
        start.isPending ||
        !history.isSuccess ||
        recovery.isError
      }
    />
  );
}

function PendingAnalysisActions({ state }: { state: AnalysisState }) {
  return (
    <AnalysisActions
      previous={undefined}
      pending={state.start.isPending}
      failed
      disabled={state.start.isPending || state.recovery.isPending || state.recovery.isError}
    />
  );
}

function AnalysisErrors({
  state,
  history,
}: {
  state: AnalysisState;
  history: AnalysisHistory['history'];
}) {
  const { recovery, start } = state;
  return (
    <>
      {recovery.isError && (
        <QueryError
          error={recovery.error}
          retry={() => {
            void recovery.refetch();
          }}
        />
      )}
      {history.isError && (
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
    </>
  );
}
