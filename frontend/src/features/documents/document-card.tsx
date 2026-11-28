import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { scopeKey } from '../../shared/api/client';
import { documentVersions, type Document, type DocumentVersion } from '../../shared/api/documents';
import { Button } from '../../shared/ui/button';
import { QueryError } from '../../shared/ui/query-error';
import { LatestVersionChoice } from './latest-version-choice';
import { UploadForm } from './upload-form';

export function DocumentCard({
  document,
  selected,
  toggle,
}: {
  document: Document;
  selected: ReadonlySet<string>;
  toggle: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const versions = useQuery({
    queryKey: [...scopeKey, 'documents', document.file_id, 'versions'],
    queryFn: () => documentVersions(document.file_id),
    enabled: expanded,
  });
  return (
    <article className="surface-card document-card">
      <div className="section-heading">
        <div>
          <h2>{document.name}</h2>
          <span className="notice">
            Добавлен {new Date(document.created_at).toLocaleString('ru-RU')}
          </span>
        </div>
        <Button
          variant="outline"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
          aria-label={`История версий ${document.name}`}
        >
          История версий
        </Button>
      </div>
      <LatestVersionChoice
        latest={document.latest_version}
        versions={versions.data}
        selected={selected}
        toggle={toggle}
        name={document.name}
      />
      {expanded && (
        <>
          {versions.isPending && <p role="status">Загружаем версии…</p>}
          {versions.isError && (
            <QueryError
              error={versions.error}
              retry={() => {
                void versions.refetch();
              }}
            />
          )}
          {versions.data && (
            <div className="table-scroll">
              <table className="workspace-table">
                <caption className="sr-only">Версии {document.name}</caption>
                <thead>
                  <tr>
                    <th>Анализ</th>
                    <th>Версия</th>
                    <th>Тип и размер</th>
                    <th>Загружена</th>
                  </tr>
                </thead>
                <tbody>
                  {versions.data.map((version) => (
                    <VersionRow
                      key={version.version_id}
                      version={version}
                      selected={selected.has(version.version_id)}
                      toggle={toggle}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <UploadForm fileId={document.file_id} name={document.name} />
        </>
      )}
    </article>
  );
}

function VersionRow({
  version,
  selected,
  toggle,
}: {
  version: DocumentVersion;
  selected: boolean;
  toggle: (id: string) => void;
}) {
  const id = version.version_id;
  const [search] = useSearchParams();
  const destination = new URLSearchParams(search);
  destination.set('version', id);
  destination.delete('fragment');
  return (
    <tr>
      <td>
        <input
          type="checkbox"
          checked={selected}
          aria-label={`Анализировать ${version.original_name} · ${id}`}
          onChange={() => toggle(id)}
        />
      </td>
      <td>
        <Link className="text-link" to={`/documents?${destination.toString()}`}>
          {version.original_name} · {id.slice(0, 8)}
        </Link>
      </td>
      <td>
        {version.mime_type}
        <br />
        <span>{version.size.toLocaleString('ru-RU')} Б</span>
      </td>
      <td>{new Date(version.uploaded_at).toLocaleString('ru-RU')}</td>
    </tr>
  );
}
