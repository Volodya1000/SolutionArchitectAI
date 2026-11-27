import { useSearchParams } from 'react-router';
import { useClarifications } from '../../shared/api/use-clarifications';
export function useAnalysisContext(newHistory: boolean) {
  const [search] = useSearchParams();
  const runId = search.get('run');
  const query = useClarifications(runId ?? '', Boolean(runId));
  return {
    query,
    historyId: query.data?.history_id ?? null,
    ready: !runId || query.isSuccess || newHistory,
    loading: Boolean(runId) && query.isPending,
  };
}
