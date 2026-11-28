import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { scopeKey } from './client';
import { readClarifications } from './clarifications';
import { announceClarificationChange, useClarificationSync } from './clarification-sync';
import { type ExtractionSummary } from './extractions';

export const clarificationKey = (run: string) => [...scopeKey, 'clarifications', run];
export function useClarifications(
  run: string,
  enabled = true,
  status?: ExtractionSummary['status'],
) {
  useClarificationSync();
  const client = useQueryClient();
  useEffect(() => {
    if (
      !enabled ||
      !status ||
      !['waiting_input', 'completed', 'failed', 'cancelled'].includes(status)
    )
      return;
    let current = true;
    const filter = { queryKey: clarificationKey(run), exact: true };
    // A request started while running may still contain the pre-review snapshot.
    void client.cancelQueries(filter).then(() => {
      if (current) return client.invalidateQueries(filter);
    });
    return () => {
      current = false;
    };
  }, [client, run, enabled, status]);
  return useQuery({
    queryKey: clarificationKey(run),
    queryFn: () => readClarifications(run),
    enabled,
    retry: false,
    refetchInterval: (query) => (query.state.data?.resume_pending ? 2000 : false),
    refetchOnWindowFocus: 'always',
  });
}
export function useInvalidateClarifications() {
  const client = useQueryClient();
  return async () => {
    await client.invalidateQueries({ queryKey: scopeKey });
    announceClarificationChange();
  };
}
