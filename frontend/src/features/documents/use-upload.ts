import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { scopeKey } from '../../shared/api/client';
import { ApiError } from '../../shared/api/api-error';
import { readUploadOperation, uploadDocument } from '../../shared/api/documents';
import {
  describeUpload,
  sameUpload,
  uploadDescription,
  type UploadDescription,
} from './saved-work';

type SelectedUpload = { file: File; description: UploadDescription };

export function useUpload(fileId: string | null) {
  const client = useQueryClient();
  const [saved, setSaved] = useState(() => uploadDescription.read(fileId));
  const [selected, setSelected] = useState<SelectedUpload | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: [...scopeKey, 'documents'] });
  const recovery = useQuery({
    queryKey: [...scopeKey, 'upload-operation', saved?.operationId],
    enabled: saved !== null,
    retry: false,
    queryFn: async () => {
      if (!saved) return null;
      const operation = await readUploadOperation(saved.operationId);
      if (operation?.stage === 'completed') {
        uploadDescription.clear(saved);
        await refresh();
      }
      return operation;
    },
  });
  const completed = recovery.data?.stage === 'completed';
  const selection = useMutation({
    mutationFn: async (file: File) => {
      const description = await describeUpload(file, fileId);
      if (saved && !completed) {
        if (!sameUpload(saved, description))
          throw new Error(
            'Выберите тот же файл: имя, размер и содержимое должны совпадать с незавершённой загрузкой.',
          );
        return { file, description: saved };
      }
      return { file, description };
    },
    onSuccess: setSelected,
  });
  const upload = useMutation({
    mutationFn: async ({ file, description }: SelectedUpload) => {
      const pending = uploadDescription.read(fileId);
      if (pending) {
        const operation = await readUploadOperation(pending.operationId);
        if (operation?.stage === 'completed') return operation.version;
      }
      uploadDescription.save(description);
      setSaved(description);
      try {
        return await uploadDocument({ file, fileId, operationId: description.operationId });
      } catch (error) {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          uploadDescription.clear(description);
          setSaved(null);
        }
        throw error;
      }
    },
    onSuccess: async (_version, command) => {
      uploadDescription.clear(command.description);
      setSaved(null);
      setSelected(null);
      await refresh();
    },
  });
  function select(file: File | undefined) {
    setSelected(null);
    upload.reset();
    selection.reset();
    if (file) selection.mutate(file);
  }
  const checking = selection.isPending || (saved !== null && recovery.isPending);
  const error = selection.error ?? upload.error;
  return { saved, selected, selection, recovery, completed, upload, select, checking, error };
}
