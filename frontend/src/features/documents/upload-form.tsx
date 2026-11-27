import { useId } from 'react';
import { Button } from '../../shared/ui/button';
import { QueryError } from '../../shared/ui/query-error';
import { useUpload } from './use-upload';

type UploadState = ReturnType<typeof useUpload>;

export function UploadForm({
  fileId = null,
  name = '',
}: {
  fileId?: string | null;
  name?: string;
}) {
  const inputId = useId();
  const state = useUpload(fileId);
  const { selected, upload, select, checking } = state;
  const action = fileId ? 'Загрузить редакцию' : 'Загрузить документ';
  return (
    <form
      className="upload-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (selected) upload.mutate(selected);
      }}
    >
      <label htmlFor={inputId}>{fileId ? `Новая редакция ${name}` : 'Новый документ'}</label>
      <input
        id={inputId}
        type="file"
        accept=".txt,.md,.markdown,.pdf,.docx"
        disabled={upload.isPending || checking}
        onChange={(event) => {
          select(event.target.files?.[0]);
        }}
      />
      <UploadButton state={state} action={action} />
      <UploadFeedback state={state} />
    </form>
  );
}

function UploadButton({ state, action }: { state: UploadState; action: string }) {
  const { selected, upload, saved, completed, checking, recovery } = state;
  return (
    <Button
      type="submit"
      variant="outline"
      disabled={!selected || upload.isPending || checking || recovery.isError}
    >
      {upload.isPending ? 'Сохраняем версию…' : saved && !completed ? 'Повторить загрузку' : action}
    </Button>
  );
}

function UploadFeedback({ state }: { state: UploadState }) {
  const { saved, completed, checking, recovery, error, upload } = state;
  return (
    <>
      {saved && !completed && (
        <p className="notice" role="status">
          {checking
            ? 'Проверяем результат предыдущей загрузки…'
            : `Незавершённая загрузка ${saved.name}. Для повтора выберите тот же файл.`}
        </p>
      )}
      {recovery.isError && (
        <QueryError
          error={recovery.error}
          retry={() => {
            void recovery.refetch();
          }}
        />
      )}
      {error && (
        <p className="notice error-text" role="alert">
          {error.message}
        </p>
      )}
      {(upload.isSuccess || completed) && (
        <p className="notice" role="status">
          Версия сохранена. Ранее загруженные версии доступны в истории.
        </p>
      )}
    </>
  );
}
