import { Link } from 'react-router';
import { locatorText } from '../../shared/api/documents';
import type { SourceRef } from '../../shared/api/extractions';

export function Evidence({
  sources,
  originalText,
  runId,
}: {
  sources: SourceRef[];
  originalText: string;
  runId: string;
}) {
  const hasQuote = sources.some((source) => source.quote.trim().length > 0);
  return (
    <>
      {sources.length === 0 && <p className="evidence-warning">Источник не подтверждён</p>}
      <ul className="evidence-list">
        {sources.map((source, index) => (
          <li key={`${source.fragment_id}-${index}`}>
            {(source.status !== 'verified' || !source.quote.trim()) && (
              <p className="evidence-warning">Цитата не подтверждена исходным текстом.</p>
            )}
            {source.version_id && source.locator ? (
              <Link
                className="text-link"
                to={`/documents?version=${encodeURIComponent(source.version_id)}&fragment=${encodeURIComponent(source.fragment_id)}&run=${encodeURIComponent(runId)}`}
              >
                Источник · {locatorText(source.locator)}
              </Link>
            ) : (
              <p className="notice">Подтверждающий фрагмент недоступен.</p>
            )}
            {source.quote.trim() && (
              <details>
                <summary>Цитата из документа</summary>
                <blockquote>{source.quote}</blockquote>
                <details>
                  <summary>Технические сведения</summary>
                  <p className="version-meta">Версия {source.version_id}</p>
                  <p className="version-meta">SHA-256: {source.sha256}</p>
                </details>
              </details>
            )}
          </li>
        ))}
      </ul>
      {!hasQuote && (
        <details>
          <summary>Исходная формулировка</summary>
          <blockquote>{originalText}</blockquote>
        </details>
      )}
    </>
  );
}
