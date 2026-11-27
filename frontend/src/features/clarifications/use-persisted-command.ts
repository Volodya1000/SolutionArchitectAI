import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { z } from 'zod';
import { ApiError } from '../../shared/api/api-error';
import { scopeKey } from '../../shared/api/client';
import { savedValue } from './saved-command';

export function usePersistedCommand<C extends { operation_id: string }, R>(options: {
  key: string;
  schema: z.ZodType<C>;
  recover: (id: string) => Promise<R | null>;
  execute: (command: C) => Promise<R>;
  onSuccess: (result: R) => Promise<void>;
  onConflict?: () => Promise<void>;
}) {
  const store = savedValue(options.key, options.schema);
  const [pending, setPending] = useState(() => store.read());
  const recovery = useQuery({
    queryKey: [...scopeKey, 'command', options.key, pending?.operation_id],
    queryFn: () => (pending ? options.recover(pending.operation_id) : Promise.resolve(null)),
    enabled: pending !== null,
    retry: false,
  });
  const mutation = useMutation({
    retry: false,
    mutationFn: async (command: C) => {
      const recovered = await options.recover(command.operation_id);
      return recovered ?? options.execute(command);
    },
    onSuccess: async (result) => {
      store.clear();
      setPending(null);
      await options.onSuccess(result);
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
        store.clear();
        setPending(null);
        await options.onConflict?.();
      }
    },
  });
  function submit(command: C) {
    const original = pending ?? command;
    store.save(original);
    setPending(original);
    mutation.mutate(original);
  }
  return { pending, recovery, mutation, submit };
}
