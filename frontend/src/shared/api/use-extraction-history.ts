import {
  useInfiniteQuery,
  useQuery,
  type InfiniteData,
  type QueryClient,
} from '@tanstack/react-query';
import { scopeKey } from './client';
import {
  extractionActive,
  extractionHistory,
  extractionSummarySchema,
  readExtractionStatus,
  type Extraction,
  type ExtractionPage,
  type ExtractionSummary,
} from './extractions';

export const extractionHistoryKey = [...scopeKey, 'extraction-history'];
export const extractionStatusKey = (id: string) => [...scopeKey, 'extraction-status', id];

export function useExtractionHistory() {
  const history = useInfiniteQuery({
    queryKey: extractionHistoryKey,
    queryFn: ({ pageParam }) => extractionHistory(pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, _pages, offset) =>
      last.has_more ? offset + last.items.length : undefined,
  });
  return { history, runs: history.data?.pages.flatMap((page) => page.items) ?? [] };
}

export function useExtractionStatus(id: string, initial?: ExtractionSummary) {
  return useQuery({
    queryKey: extractionStatusKey(id),
    queryFn: () => readExtractionStatus(id),
    initialData: initial,
    refetchInterval: (query) =>
      query.state.data &&
      (extractionActive(query.state.data) || query.state.data.status === 'waiting_input')
        ? 1000
        : false,
  });
}

export function recordExtraction(client: QueryClient, run: Extraction) {
  const summary = extractionSummarySchema.parse(run);
  client.setQueryData(extractionStatusKey(run.id), summary);
  if (!extractionActive(run)) client.setQueryData([...scopeKey, 'extraction', run.id], run);
  client.setQueryData<InfiniteData<ExtractionPage, number>>(extractionHistoryKey, (old) => {
    if (!old) return old;
    const pages = old.pages;
    return {
      pageParams: old.pageParams,
      pages: pages.map((page) => ({
        ...page,
        items: page.items.map((item) => (item.id === run.id ? summary : item)),
      })),
    };
  });
  void client.invalidateQueries({ queryKey: extractionHistoryKey });
}
