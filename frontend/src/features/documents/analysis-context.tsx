import { QueryError } from '../../shared/ui/query-error';
import { useAnalysisContext } from './use-analysis-context';
export function AnalysisContextStatus({
  context,
  newHistory,
}: {
  context: ReturnType<typeof useAnalysisContext>;
  newHistory: boolean;
}) {
  return (
    <>
      {context.historyId && !newHistory && (
        <p className="notice">
          Используется история выбранного анализа. Сохранённые ответы останутся доступны.
        </p>
      )}
      {newHistory && (
        <p className="notice">
          Новая история уточнений начнётся без прежних ответов. Предыдущая история сохранится.
        </p>
      )}
      {context.loading && <p role="status">Загружаем историю уточнений выбранного анализа…</p>}
      {context.query.isError && (
        <QueryError
          error={context.query.error}
          retry={() => {
            void context.query.refetch();
          }}
        />
      )}
    </>
  );
}
