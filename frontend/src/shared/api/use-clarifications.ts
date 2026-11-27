import { useQuery, useQueryClient } from '@tanstack/react-query';
import { scopeKey } from './client';
import { readClarifications } from './clarifications';

export const clarificationKey = (run: string) => [...scopeKey, 'clarifications', run];
export function useClarifications(run: string, enabled = true) {
  return useQuery({
    queryKey: clarificationKey(run),
    queryFn: () => readClarifications(run),
    enabled,
    retry: false,
    refetchInterval: 2000,
  });
}
export function useInvalidateClarifications() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: scopeKey });
}
