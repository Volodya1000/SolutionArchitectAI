import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import {
  request,
  runSchema,
  scopeKey,
  snapshotSchema,
  terminal,
  type Snapshot,
} from '../../shared/api/client';
import { sessionStore } from '../../shared/ui/session-storage';
import {
  InputValidationError,
  MESSAGE_LIMIT,
  MESSAGE_LIMIT_HINT,
  messageLength,
} from '../../shared/api/validation';
import { readPending, savePending } from './pending-command';
import { subscribeToRun } from './run-events';
import { reconcileHistory } from './stream';

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
    structuralSharing: (current, incoming) =>
      reconcileHistory(current as Snapshot | undefined, incoming as Snapshot),
  });
  const [failedRunId, setFailedRunId] = useState<string>();
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
      if (sessionStore.get(`draft:${chatId}`) === content) sessionStore.remove(`draft:${chatId}`);
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
    return subscribeToRun(client, chatId, runId, (failed) =>
      setFailedRunId(failed ? runId : undefined),
    );
  }, [chatId, runId, client, online]);
  return {
    query,
    run,
    send,
    cancel,
    connectionError: Boolean(run) && (failedRunId === runId || !online),
    pending,
  };
}
