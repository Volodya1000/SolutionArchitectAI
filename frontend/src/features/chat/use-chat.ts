import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { request, runSchema, scopeKey, snapshotSchema, terminal } from '../../shared/api/client';
import {
  InputValidationError,
  MESSAGE_LIMIT,
  MESSAGE_LIMIT_HINT,
  messageLength,
} from '../../shared/api/validation';
import { readPending, savePending } from './pending-command';
import { subscribeToRun } from './run-events';

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
  const pending = useRef(readPending(chatId));
  const run = query.data?.runs.find((item) => !terminal(item));
  const runId = run?.id;
  const refresh = () => client.invalidateQueries({ queryKey: key });
  const send = useMutation({
    mutationFn: async (content: string) => {
      if (messageLength(content) > MESSAGE_LIMIT)
        throw new InputValidationError(MESSAGE_LIMIT_HINT);
      if (pending.current?.content !== content)
        pending.current = { command_id: crypto.randomUUID(), content };
      savePending(chatId, pending.current);
      const value = await request(`/chats/${chatId}/runs`, runSchema, {
        method: 'POST',
        body: JSON.stringify(pending.current),
      });
      pending.current = null;
      savePending(chatId, null);
      return value;
    },
    onError: (error) => {
      if (error instanceof InputValidationError) {
        pending.current = null;
        savePending(chatId, null);
      }
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
    return subscribeToRun(client, chatId, runId, setConnectionError);
  }, [chatId, runId, client, online]);
  return {
    query,
    run,
    send,
    cancel,
    connectionError: Boolean(run) && (connectionError || !online),
    pending,
  };
}
