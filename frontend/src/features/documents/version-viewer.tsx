import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { scopeKey } from '../../shared/api/client';
import {
  locatorText,
  parsedVersion,
  parserWarningText,
  readVersion,
  type ParsedDocument,
} from '../../shared/api/documents';
import { useSearchParams } from 'react-router';
import { DiscussButton } from '../clarifications';
import { QueryError } from '../../shared/ui/query-error';

export function VersionViewer({
  versionId,
  fragmentId,
}: {
  versionId: string;
  fragmentId: string | null;
}) {
  const version = useQuery({
    queryKey: [...scopeKey, 'version', versionId],
    queryFn: () => readVersion(versionId),
  });
  const parsed = useQuery({
    queryKey: [...scopeKey, 'parsed', versionId],
    queryFn: () => parsedVersion(versionId),
  });
  return (
    <section className="surface-card source-viewer" aria-label={`Версия ${versionId}`}>
      <div className="section-heading">
        <h2>Версия {versionId}</h2>
        <a
          className="text-link"
          href={`/api/document-versions/${encodeURIComponent(versionId)}/content`}
          download
        >
          Скачать оригинал
        </a>
      </div>
      {version.data && (
        <p className="version-meta">
          {version.data.original_name} · {version.data.mime_type}
          <br />
          <span>SHA-256: {version.data.sha256}</span>
        </p>
      )}
      {parsed.isPending && <p role="status">Извлекаем сохранённый текст…</p>}
      {parsed.isError && (
        <QueryError
          error={parsed.error}
          retry={() => {
            void parsed.refetch();
          }}
        />
      )}
      {version.isError && !parsed.isError && (
        <QueryError
          error={version.error}
          retry={() => {
            void version.refetch();
          }}
        />
      )}
      {parsed.data && <SourceFragments parsed={parsed.data} fragmentId={fragmentId} />}
    </section>
  );
}

function SourceFragments({
  parsed,
  fragmentId,
}: {
  parsed: ParsedDocument;
  fragmentId: string | null;
}) {
  const [search] = useSearchParams();
  const selected = useRef<HTMLElement>(null);
  const hasFragment = parsed.fragments.some((fragment) => fragment.fragment_id === fragmentId);
  const separatorLines = new Set(parsed.structure?.tables.map((table) => table.delimiter_line));
  useEffect(() => {
    if (fragmentId) {
      selected.current?.scrollIntoView({ block: 'center' });
      selected.current?.focus();
    }
  }, [fragmentId, parsed]);
  return (
    <>
      <p className="notice">
        Сохранённый разбор · {parsed.parser_version}. Текст документа показан как недоверенные
        данные.
      </p>
      {parsed.warnings.map((warning) => (
        <p className="notice evidence-warning" role="status" key={warning}>
          {parserWarningText(warning)}
        </p>
      ))}
      {fragmentId && !hasFragment && (
        <p className="notice error-text" role="alert">
          Указанный фрагмент отсутствует в этой версии. Другой источник не подставляется.
        </p>
      )}
      <div className="source-fragments">
        {parsed.fragments.map((fragment) => {
          if (fragment.locator.kind === 'lines' && separatorLines.has(fragment.locator.start)) {
            return fragment.fragment_id === fragmentId ? (
              <section
                key={fragment.fragment_id}
                ref={selected}
                tabIndex={-1}
                aria-label={locatorText(fragment.locator)}
              >
                <pre>{fragment.text}</pre>
              </section>
            ) : null;
          }
          return (
            <article
              key={fragment.fragment_id}
              ref={fragment.fragment_id === fragmentId ? selected : undefined}
              tabIndex={-1}
              className={
                fragment.fragment_id === fragmentId
                  ? 'source-fragment selected-fragment'
                  : 'source-fragment'
              }
              aria-label={locatorText(fragment.locator)}
            >
              <div className="fragment-locator">{locatorText(fragment.locator)}</div>
              <p>{fragment.text}</p>
              <DiscussButton
                subject={{
                  kind: 'source',
                  version_id: parsed.version_id,
                  fragment_id: fragment.fragment_id,
                  analysis_id: search.get('run'),
                }}
              />
            </article>
          );
        })}
      </div>
    </>
  );
}
