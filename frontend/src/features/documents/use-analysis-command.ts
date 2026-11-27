import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { scopeKey } from '../../shared/api/client';
import { ApiError } from '../../shared/api/api-error';
import {
  readExtractionOperation,
  startExtraction,
  type Extraction,
  type ExtractionCommand,
} from '../../shared/api/extractions';
import { extractionCommand } from './saved-work';

export function useAnalysisCommand(onSuccess: (run: Extraction) => Promise<void>) {
  const [pending, setPending] = useState(extractionCommand.read);
  const recovery = useQuery({
    queryKey: [...scopeKey, 'extraction-operation', pending?.operation_id],
    enabled: pending !== null,
    retry: false,
    queryFn: () =>
      pending ? readExtractionOperation(pending.operation_id) : Promise.resolve(null),
  });
  const start = useMutation({
    mutationFn: async (command: ExtractionCommand) => {
      const saved = extractionCommand.read();
      if (saved?.operation_id === command.operation_id) {
        const run = await readExtractionOperation(saved.operation_id);
        if (run) return run;
      }
      extractionCommand.save(command);
      try {
        return await startExtraction(command);
      } catch (error) {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          extractionCommand.clear(command.operation_id);
          setPending(null);
        }
        throw error;
      }
    },
    onSuccess: async (run, command) => {
      extractionCommand.clear(command.operation_id);
      setPending(null);
      await onSuccess(run);
    },
  });
  function submit(selected: ReadonlySet<string>, scope: string) {
    const saved = recovery.data ? null : pending;
    const command = saved ?? {
      operation_id: crypto.randomUUID(),
      version_ids: [...selected].sort(),
      analysis_scope: scope.trim(),
    };
    setPending(command);
    start.mutate(command);
  }
  return { pending, recovery, start, submit };
}
