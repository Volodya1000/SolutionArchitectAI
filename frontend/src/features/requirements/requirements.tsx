import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { scopeKey } from '../../shared/api/client';
import {
  extractionActive,
  readExtraction,
  type ExtractionSummary,
} from '../../shared/api/extractions';
import { useExtractionHistory, useExtractionStatus } from '../../shared/api/use-extraction-history';
import { QueryError } from '../../shared/ui/query-error';
import { Button } from '../../shared/ui/button';
import { RunStatus } from './run-status';
import { RunResult } from './run-result';
import { ReviewCoverage } from './review-coverage';

export function Requirements() {
  const [search, setSearch] = useSearchParams();
  const { history, runs } = useExtractionHistory();
  const selectedId = search.get('run') ?? runs[0]?.id;
  return (
    <div className="workspace-content">
      <div className="page-intro">
        <h1>Требования</h1>
        <p>
          Результаты анализа — кандидаты для проверки. Цитаты сверены с исходным текстом; это не
          подтверждает правильность формулировок и категорий.
        </p>
        <Link
          className="text-link"
          to={selectedId ? `/documents?run=${encodeURIComponent(selectedId)}` : '/documents'}
        >
          Выбрать документы для нового анализа
        </Link>
      </div>
      {history.isPending && <p role="status">Загружаем историю извлечений…</p>}
      {history.isError && (
        <QueryError
          error={history.error}
          retry={() => {
            void history.refetch();
          }}
        />
      )}
      {history.data && (
        <ExtractionHistory
          runs={runs}
          selectedId={selectedId}
          select={(id) => setSearch({ run: id })}
        />
      )}
      {history.hasNextPage && (
        <Button
          variant="outline"
          disabled={history.isFetchingNextPage}
          onClick={() => {
            void history.fetchNextPage();
          }}
        >
          Загрузить ещё анализы
        </Button>
      )}
      {selectedId && (
        <RunPanel
          key={selectedId}
          id={selectedId}
          initial={runs.find((run) => run.id === selectedId)}
        />
      )}
    </div>
  );
}

function ExtractionHistory({
  runs,
  selectedId,
  select,
}: {
  runs: ExtractionSummary[];
  selectedId: string | undefined;
  select: (id: string) => void;
}) {
  if (runs.length === 0)
    return selectedId ? null : (
      <p className="notice">Извлечений пока нет. Загрузите документы и запустите анализ.</p>
    );
  return (
    <label className="field-label">
      История извлечений
      <select
        aria-label="История извлечений"
        value={selectedId}
        onChange={(event) => select(event.target.value)}
      >
        {selectedId && !runs.some((run) => run.id === selectedId) && (
          <option value={selectedId}>Выбранный анализ · {selectedId.slice(0, 8)}</option>
        )}
        {runs.map((run) => (
          <option key={run.id} value={run.id}>
            {new Date(run.created_at).toLocaleString('ru-RU')} · {run.model}
          </option>
        ))}
      </select>
    </label>
  );
}

function RunPanel({ id, initial }: { id: string; initial: ExtractionSummary | undefined }) {
  const status = useExtractionStatus(id, initial);
  const run = useQuery({
    queryKey: [...scopeKey, 'extraction', id],
    queryFn: () => readExtraction(id),
    enabled: status.data ? !extractionActive(status.data) : false,
    staleTime: 0,
  });
  return (
    <>
      {status.isPending && <p role="status">Загружаем состояние анализа…</p>}
      {status.isError && (
        <QueryError
          error={status.error}
          retry={() => {
            void status.refetch();
          }}
        />
      )}
      {status.data && <RunStatus run={status.data} coverage={run.data?.coverage} />}
      {status.data && <ReviewCoverage run={status.data} />}
      {run.isFetching && <p role="status">Загружаем результат…</p>}
      {run.isError && (
        <QueryError
          error={run.error}
          retry={() => {
            void run.refetch();
          }}
        />
      )}
      {run.data && <RunResult run={run.data} />}
    </>
  );
}
