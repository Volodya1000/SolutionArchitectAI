import type { UseQueryResult } from '@tanstack/react-query';
import type { DocumentVersion } from '../../shared/api/documents';
import { QueryError } from '../../shared/ui/query-error';

export function LatestVersionChoice({
  query,
  selected,
  toggle,
  name,
}: {
  query: UseQueryResult<DocumentVersion[]>;
  selected: ReadonlySet<string>;
  toggle: (id: string) => void;
  name: string;
}) {
  if (query.isPending) return <p role="status">Загружаем версии…</p>;
  if (query.isError)
    return (
      <QueryError
        error={query.error}
        retry={() => {
          void query.refetch();
        }}
      />
    );
  const latest = query.data[0];
  if (!latest) return <p className="notice">У документа пока нет сохранённых версий.</p>;
  const olderSelected = query.data.slice(1).some((version) => selected.has(version.version_id));
  return (
    <div className="document-selection">
      <label className="version-choice">
        <input
          type="checkbox"
          aria-label={`Выбрать последнюю версию ${name}`}
          checked={selected.has(latest.version_id)}
          onChange={() => toggle(latest.version_id)}
        />
        <span>
          Выбрать для анализа
          <small>Последняя версия · {new Date(latest.uploaded_at).toLocaleString('ru-RU')}</small>
        </span>
      </label>
      {olderSelected && <p className="notice">Выбраны предыдущие версии — доступны в истории.</p>}
    </div>
  );
}
