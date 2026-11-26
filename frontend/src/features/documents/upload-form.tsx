import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useId, useState } from 'react';
import { scopeKey } from '../../shared/api/client';
import { uploadDocument, type UploadCommand } from '../../shared/api/documents';
import { Button } from '../../shared/ui/button';

export function UploadForm({
  fileId = null,
  name = '',
}: {
  fileId?: string | null;
  name?: string;
}) {
  const inputId = useId();
  const client = useQueryClient();
  const [command, setCommand] = useState<UploadCommand | null>(null);
  const upload = useMutation({
    mutationFn: uploadDocument,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: [...scopeKey, 'documents'] });
      setCommand(null);
    },
  });
  const action = fileId ? 'Загрузить редакцию' : 'Загрузить документ';
  return (
    <form
      className="upload-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (command) upload.mutate(command);
      }}
    >
      <label htmlFor={inputId}>{fileId ? `Новая редакция ${name}` : 'Новый документ'}</label>
      <input
        id={inputId}
        type="file"
        accept=".txt,.md,.markdown,.pdf,.docx"
        disabled={upload.isPending}
        onChange={(event) => {
          const file = event.target.files?.[0];
          upload.reset();
          setCommand(file ? { file, fileId, operationId: crypto.randomUUID() } : null);
        }}
      />
      <Button type="submit" variant="outline" disabled={!command || upload.isPending}>
        {upload.isPending ? 'Сохраняем версию…' : upload.isError ? 'Повторить загрузку' : action}
      </Button>
      {upload.isError && (
        <p className="notice error-text" role="alert">
          {upload.error.message}
        </p>
      )}
      {upload.isSuccess && (
        <p className="notice" role="status">
          Версия сохранена. Ранее загруженные версии доступны в истории.
        </p>
      )}
    </form>
  );
}
