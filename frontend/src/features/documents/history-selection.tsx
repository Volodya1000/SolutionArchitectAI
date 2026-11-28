import { useSearchParams } from 'react-router';
import { useExtractionHistory } from '../../shared/api/use-extraction-history';
import { Button } from '../../shared/ui/button';

export function HistorySelection({ disabled }: { disabled: boolean }) {
  const [search, setSearch] = useSearchParams();
  const { runs, history } = useExtractionHistory();
  const selected = search.get('historyRun') ?? search.get('run') ?? '';
  return (
    <>
      <label className="field-label">
        История уточнений
        <select
          value={selected}
          disabled={disabled}
          onChange={(event) => {
            const next = new URLSearchParams(search);
            next.set('historyRun', event.target.value);
            void setSearch(next);
          }}
        >
          <option value="">Общая история задачи</option>
          {selected && !runs.some((run) => run.id === selected) && (
            <option value={selected}>История выбранного анализа</option>
          )}
          {runs.map((run) => (
            <option key={run.id} value={run.id}>
              История анализа от {new Date(run.created_at).toLocaleString('ru-RU')} · {run.model}
            </option>
          ))}
        </select>
      </label>
      {history.hasNextPage && (
        <Button
          type="button"
          variant="ghost"
          disabled={history.isFetchingNextPage}
          onClick={() => {
            void history.fetchNextPage();
          }}
        >
          Загрузить ещё истории
        </Button>
      )}
    </>
  );
}
