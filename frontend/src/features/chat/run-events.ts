import type { QueryClient } from '@tanstack/react-query';
import { envelopeSchema, scopeKey, terminal, type Snapshot } from '../../shared/api/client';
import { mergeSnapshot } from './stream';

export function subscribeToRun(
  client: QueryClient,
  chatId: string,
  runId: string,
  connectionError: (value: boolean) => void,
): () => void {
  const key = [...scopeKey, 'chat', chatId];
  let events: EventSource;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;

  function recover() {
    if (disposed) return;
    events.close();
    connectionError(true);
    void client.invalidateQueries({ queryKey: key });
    clearTimeout(retry);
    retry = setTimeout(connect, 1000);
  }

  function receive(event: MessageEvent<string>) {
    if (disposed) return;
    let raw: unknown;
    try {
      raw = JSON.parse(event.data);
    } catch {
      recover();
      return;
    }
    const parsed = envelopeSchema.safeParse(raw);
    if (
      !parsed.success ||
      parsed.data.run_id !== runId ||
      parsed.data.payload.id !== runId ||
      parsed.data.payload.chat_id !== chatId ||
      parsed.data.sequence !== parsed.data.payload.sequence
    ) {
      recover();
      return;
    }
    connectionError(false);
    client.setQueryData<Snapshot>(key, (current) =>
      mergeSnapshot(current, parsed.data.payload, chatId),
    );
    if (terminal(parsed.data.payload)) events.close();
  }

  function connect() {
    if (disposed) return;
    events = new EventSource(`/api/runs/${runId}/events`);
    events.onmessage = receive;
    events.onerror = recover;
  }

  connect();
  return () => {
    disposed = true;
    clearTimeout(retry);
    events.close();
  };
}
