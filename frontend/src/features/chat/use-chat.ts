import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import {
  envelopeSchema,
  request,
  runSchema,
  scopeKey,
  snapshotSchema,
  terminal,
  type Snapshot,
} from '../../shared/api/client';
import { mergeSnapshot } from './stream';

function useOnline() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
    };
  }, []);
  return online;
}

export function useChat(chatId: string) {
  const online = useOnline();
  const client = useQueryClient();
  const key = [...scopeKey, 'chat', chatId];
  const query = useQuery({
    queryKey: key,
    queryFn: () => request(`/chats/${chatId}`, snapshotSchema),
  });
  const [connectionError, setConnectionError] = useState(false);
  const pending = useRef<{ command_id: string; content: string } | null>(null);
  const run = query.data?.runs.find((item) => !terminal(item));
  const runId = run?.id;
  const refresh = () => client.invalidateQueries({ queryKey: key });
  const send = useMutation({
    mutationFn: async (content: string) => {
      if (pending.current?.content !== content)
        pending.current = { command_id: crypto.randomUUID(), content };
      const value = await request(`/chats/${chatId}/runs`, runSchema, {
        method: 'POST',
        body: JSON.stringify(pending.current),
      });
      pending.current = null;
      return value;
    },
    onSettled: refresh,
  });
  const cancel = useMutation({
    mutationFn: () => {
      if (!run) return Promise.resolve();
      return request(`/runs/${run.id}/cancel`, runSchema, { method: 'POST' }).then(() => undefined);
    },
    onSettled: refresh,
  });
  useEffect(() => {
    if (!runId || !online) return;
    const events = new EventSource(`/api/runs/${runId}/events`);
    events.onmessage = (event: MessageEvent<string>) => {
      const raw: unknown = JSON.parse(event.data);
      const parsed = envelopeSchema.safeParse(raw);
      if (!parsed.success) {
        setConnectionError(true);
        return;
      }
      setConnectionError(false);
      client.setQueryData<Snapshot>([...scopeKey, 'chat', chatId], (current) =>
        mergeSnapshot(current, parsed.data.payload, chatId),
      );
      if (terminal(parsed.data.payload)) events.close();
    };
    events.onerror = () => {
      setConnectionError(true);
      void client.invalidateQueries({ queryKey: [...scopeKey, 'chat', chatId] });
    };
    return () => events.close();
  }, [chatId, runId, client, online]);
  return { query, run, send, cancel, connectionError: connectionError || !online, pending };
}
