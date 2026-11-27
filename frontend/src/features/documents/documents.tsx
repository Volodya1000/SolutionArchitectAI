import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useSearchParams } from 'react-router';
import { scopeKey } from '../../shared/api/client';
import { documentList } from '../../shared/api/documents';
import { QueryError } from '../../shared/ui/query-error';
import { AnalysisForm } from './analysis-form';
import { DocumentCard } from './document-card';
import { UploadForm } from './upload-form';
import { VersionViewer } from './version-viewer';
import { analysisDraft } from './saved-work';

export function Documents() {
  const [search] = useSearchParams();
  const [draft, setDraft] = useState(analysisDraft.read);
  const selected: ReadonlySet<string> = new Set(draft.versionIds);
  const documents = useQuery({ queryKey: [...scopeKey, 'documents'], queryFn: documentList });
  const versionId = search.get('version');
  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    updateDraft({ ...draft, versionIds: [...next] });
  }
  function updateDraft(next: typeof draft) {
    analysisDraft.save(next);
    setDraft(next);
  }
  return (
    <div className="workspace-content">
      <div className="page-intro">
        <span className="eyebrow">ИСТОЧНИКИ ТРЕБОВАНИЙ</span>
        <h1>Документы</h1>
        <p>Каждая редакция сохраняет свой оригинал, контрольную сумму и адресуемые фрагменты.</p>
      </div>
      <section className="surface-card document-card" aria-label="Загрузка документа">
        <UploadForm />
        <p className="notice">Доступные расширения: .txt, .md, .markdown, .pdf, .docx.</p>
      </section>
      {documents.isPending && <p role="status">Загружаем документы…</p>}
      {documents.isError && (
        <QueryError
          error={documents.error}
          retry={() => {
            void documents.refetch();
          }}
        />
      )}
      {documents.data?.length === 0 && (
        <p className="notice">Документов пока нет. Загрузите исходный BRD для анализа.</p>
      )}
      <div className="document-list">
        {documents.data?.map((document) => (
          <DocumentCard
            key={document.file_id}
            document={document}
            selected={selected}
            toggle={toggle}
          />
        ))}
      </div>
      <AnalysisForm
        selected={selected}
        scope={draft.scope}
        setScope={(scope) => updateDraft({ ...draft, scope })}
      />
      {versionId && (
        <VersionViewer key={versionId} versionId={versionId} fragmentId={search.get('fragment')} />
      )}
    </div>
  );
}
