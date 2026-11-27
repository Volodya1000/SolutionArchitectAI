import type { DocumentVersion } from '../../shared/api/documents';

export function LatestVersionChoice({
  latest,
  versions,
  selected,
  toggle,
  name,
}: {
  latest: DocumentVersion | null;
  versions: DocumentVersion[] | undefined;
  selected: ReadonlySet<string>;
  toggle: (id: string) => void;
  name: string;
}) {
  if (!latest) return <p className="notice">У документа пока нет сохранённых версий.</p>;
  const olderSelected = versions?.some(
    (version) => version.version_id !== latest.version_id && selected.has(version.version_id),
  );
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
