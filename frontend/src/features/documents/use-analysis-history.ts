import { useQuery } from '@tanstack/react-query';
import { scopeKey } from '../../shared/api/client';
import { extractionActive, matchingExtractions } from '../../shared/api/extractions';

export function useAnalysisHistory(
  selected: ReadonlySet<string>,
  scope: string,
  newHistory = false,
  historyId: string | null = null,
) {
  const history = useQuery({
    queryKey: [
      ...scopeKey,
      'matching-extractions',
      [...selected].sort(),
      scope.trim(),
      newHistory,
      historyId,
    ],
    queryFn: () => matchingExtractions(selected, scope, newHistory, historyId),
    enabled: selected.size > 0 && selected.size <= 20,
    refetchInterval: (query) =>
      query.state.data?.active && extractionActive(query.state.data.active) ? 1000 : false,
  });
  const previous = choosePrevious(history.data, newHistory);
  return { history, previous };
}

function choosePrevious(
  matches: Awaited<ReturnType<typeof matchingExtractions>> | undefined,
  newHistory: boolean,
) {
  return newHistory
    ? undefined
    : (matches?.active ?? matches?.current_completed ?? matches?.latest_completed ?? undefined);
}
