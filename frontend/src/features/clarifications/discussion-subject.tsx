import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { scopeKey } from '../../shared/api/client';
import { locatorText, parsedVersion } from '../../shared/api/documents';
import { type Requirement, type SourceRef } from '../../shared/api/extractions';
import { QueryError } from '../../shared/ui/query-error';

export function RequirementSubject({
  runId,
  requirementId,
  requirements,
}: {
  runId: string;
  requirementId: string;
  requirements: Requirement[];
}) {
  const requirement = requirements.find((item) => item.id === requirementId);
  if (!requirement)
    return (
      <p className="notice error-text" role="alert">
        Требование недоступно в закреплённом анализе. Другой результат не подставляется.
      </p>
    );
  return (
    <section className="discussion-requirement" aria-label="Требование обсуждения">
      <h2>Требование</h2>
      <p className="requirement-text">{requirement.normalized_text}</p>
      <h3>Исходные цитаты</h3>
      {!requirement.sources.some((source) => source.quote.trim()) && (
        <blockquote>{requirement.original_text}</blockquote>
      )}
      {requirement.sources.map((source, index) => (
        <PinnedSource key={`${source.fragment_id}:${index}`} source={source} runId={runId} />
      ))}
    </section>
  );
}

export function SourceSubject({
  versionId,
  fragmentId,
  runId,
}: {
  versionId: string;
  fragmentId: string;
  runId: string | null;
}) {
  const query = useQuery({
    queryKey: [...scopeKey, 'parsed', versionId],
    queryFn: () => parsedVersion(versionId),
  });
  if (query.isError && !query.data)
    return (
      <QueryError
        error={query.error}
        retry={() => {
          void query.refetch();
        }}
      />
    );
  if (!query.data) return <p role="status">Загружаем закреплённый фрагмент…</p>;
  const fragment = query.data.fragments.find((item) => item.fragment_id === fragmentId);
  if (!fragment)
    return (
      <p className="notice error-text" role="alert">
        Указанный фрагмент отсутствует в закреплённой версии. Другой источник не подставляется.
      </p>
    );
  const source: SourceRef = {
    file_id: query.data.file_id,
    version_id: versionId,
    fragment_id: fragmentId,
    sha256: query.data.sha256,
    locator: fragment.locator,
    quote: fragment.text,
    status: 'verified',
    reason: null,
  };
  return (
    <section aria-label="Фрагмент обсуждения">
      {query.isError && (
        <QueryError
          error={query.error}
          retry={() => {
            void query.refetch();
          }}
        />
      )}
      <h2>Фрагмент источника</h2>
      <PinnedSource source={source} runId={runId} />
      <p className="notice">Сохранённый текст документа · {query.data.parser_version}</p>
    </section>
  );
}

export function PinnedSource({ source, runId }: { source: SourceRef; runId: string | null }) {
  const query = new URLSearchParams({
    version: source.version_id ?? '',
    fragment: source.fragment_id,
  });
  if (runId) query.set('run', runId);
  return (
    <article className="discussion-source">
      <blockquote>{source.quote}</blockquote>
      {source.version_id && source.locator ? (
        <Link className="text-link" to={`/documents?${query.toString()}`}>
          Источник · {locatorText(source.locator)}
        </Link>
      ) : (
        <p className="notice">Адресуемый источник недоступен.</p>
      )}
      <details>
        <summary>Технические сведения источника</summary>
        <p className="version-meta">
          Версия {source.version_id} · Фрагмент {source.fragment_id}
          <br />
          SHA-256: {source.sha256}
        </p>
      </details>
      {source.status !== 'verified' && (
        <p className="notice evidence-warning">Цитата не подтверждена исходным текстом.</p>
      )}
    </article>
  );
}
