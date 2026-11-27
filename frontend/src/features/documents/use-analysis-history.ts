import { useQuery } from '@tanstack/react-query';
import { scopeKey } from '../../shared/api/client';
import { extractionActive, matchingExtractions } from '../../shared/api/extractions';

export function useAnalysisHistory(selected: ReadonlySet<string>, scope: string) {
  const history = useQuery({
    queryKey: [...scopeKey, 'matching-extractions', [...selected].sort(), scope.trim()],
    queryFn: () => matchingExtractions(selected, scope),
    enabled: selected.size > 0 && selected.size <= 20,
    refetchInterval: (query) =>
      query.state.data?.active && extractionActive(query.state.data.active) ? 1000 : false,
  });
  const previous =
    history.data?.active ??
    history.data?.current_completed ??
    history.data?.latest_completed ??
    undefined;
  return { history, previous };
}
