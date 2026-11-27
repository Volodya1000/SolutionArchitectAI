import { QueryError } from '../../shared/ui/query-error';
import { useAnalysisContext } from './use-analysis-context';
export function AnalysisContextStatus({
  context,
}: {
  context: ReturnType<typeof useAnalysisContext>;
}) {
  return (
    <>
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
