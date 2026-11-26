import { Link } from 'react-router';
import { locatorText } from '../../shared/api/documents';
import type { SourceRef } from '../../shared/api/extractions';

export function Evidence({ sources }: { sources: SourceRef[] }) {
  if (sources.length === 0) return <p className="evidence-warning">Источник не подтверждён</p>;
  return (
    <ul className="evidence-list">
      {sources.map((source, index) => (
        <li key={`${source.fragment_id}-${index}`}>
          <p className={source.status === 'verified' ? 'evidence-ok' : 'evidence-warning'}>
            {source.status === 'verified'
              ? 'Ссылка технически проверена'
              : `Неподтверждённый источник · ${source.reason ?? 'нет доказательства'}`}
          </p>
          {source.version_id && source.locator ? (
            <Link
              className="text-link"
              to={`/documents?version=${encodeURIComponent(source.version_id)}&fragment=${encodeURIComponent(source.fragment_id)}`}
            >
              Открыть источник · {locatorText(source.locator)}
            </Link>
          ) : (
            <p className="notice">Подтверждающий фрагмент недоступен.</p>
          )}
          <details>
            <summary>Цитата и версия источника</summary>
            <blockquote>{source.quote}</blockquote>
            <p className="version-meta">
              Версия {source.version_id}
              <br />
              SHA-256: {source.sha256}
            </p>
          </details>
        </li>
      ))}
    </ul>
  );
}
