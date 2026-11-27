import { useQuery } from '@tanstack/react-query';
import { scopeKey } from '../../shared/api/client';
import { extractionActive, extractionList } from '../../shared/api/extractions';

export function useAnalysisHistory(selected: ReadonlySet<string>, scope: string) {
  const history = useQuery({
    queryKey: [...scopeKey, 'extractions'],
    queryFn: extractionList,
    refetchInterval: (query) => (query.state.data?.some(extractionActive) ? 1000 : false),
  });
  const matching = history.data?.filter(
    (run) =>
      run.analysis_scope === scope.trim() &&
      run.version_ids.length === selected.size &&
      run.version_ids.every((id) => selected.has(id)),
  );
  const previous =
    matching?.find(extractionActive) ??
    matching?.find((run) => run.status === 'completed' && run.configuration_current) ??
    matching?.find((run) => run.status === 'completed');
  return { history, previous };
}
