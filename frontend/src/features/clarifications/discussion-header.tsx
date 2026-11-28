import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { scopeKey } from '../../shared/api/client';
import {
  readDiscussion,
  readDiscussionClarifications,
  type DiscussionBinding,
} from '../../shared/api/discussions';
import { type ClarificationView } from '../../shared/api/clarifications';
import { QueryError } from '../../shared/ui/query-error';
import { ClarificationContent } from './clarifications';
import { RequirementSubject, SourceSubject } from './discussion-subject';

export function DiscussionHeader({ chatId }: { chatId: string }) {
  const query = useQuery({
    queryKey: [...scopeKey, 'discussion', chatId],
    queryFn: () => readDiscussion(chatId),
    retry: false,
  });
  if (query.isError)
    return (
      <QueryError
        error={query.error}
        retry={() => {
          void query.refetch();
        }}
      />
    );
  const subject = query.data;
  if (!subject) return null;
  return (
    <aside className="discussion-context" aria-label="Предмет и источники обсуждения">
      <header className="surface-card discussion-subject">
        <strong>{subject.title}</strong>
        <p className="notice">Закреплено версий: {subject.version_ids.length}</p>
        <details>
          <summary>Технические сведения обсуждения</summary>
          <dl className="metadata-grid version-meta">
            <dt>Версии</dt>
            <dd>{subject.version_ids.join(', ')}</dd>
            {subject.history_id && (
              <>
                <dt>История</dt>
                <dd>{subject.history_id}</dd>
              </>
            )}
          </dl>
        </details>
        <Link className="text-link" to={subject.backlink}>
          Вернуться к {subject.kind === 'requirement' ? 'требованию' : 'источнику'}
        </Link>
      </header>
      <details className="discussion-details" open>
        <summary>Предмет, источники и уточнения</summary>
        <div className="discussion-details-content">
          <p className="notice">
            Переписка не сохраняет ответ на вопрос. Используйте явную команду в карточке.
          </p>
          <ScopedDiscussion subject={subject} />
        </div>
      </details>
    </aside>
  );
}

function ScopedDiscussion({ subject }: { subject: DiscussionBinding }) {
  const query = useQuery({
    queryKey: [...scopeKey, 'discussion-clarifications', subject.chat_id],
    queryFn: () => readDiscussionClarifications(subject.chat_id),
    retry: false,
    refetchInterval: 2000,
  });
  return (
    <>
      {query.isPending && <p role="status">Загружаем контекст обсуждения…</p>}
      {query.isError && (
        <QueryError
          error={query.error}
          retry={() => {
            void query.refetch();
          }}
        />
      )}
      {(subject.kind === 'source' || query.isSuccess) && (
        <BoundSubject subject={subject} view={query.data ?? null} />
      )}
      {query.data && <ClarificationContent view={query.data} />}
    </>
  );
}

function BoundSubject({
  subject,
  view,
}: {
  subject: DiscussionBinding;
  view: ClarificationView | null;
}) {
  if (subject.kind === 'requirement')
    return subject.analysis_id && subject.requirement_id ? (
      <RequirementSubject
        key={`${subject.analysis_id}:${subject.requirement_id}`}
        runId={subject.analysis_id}
        requirementId={subject.requirement_id}
        requirements={view?.requirements ?? []}
      />
    ) : (
      <p role="alert">Привязка требования недоступна.</p>
    );
  return subject.version_id && subject.fragment_id ? (
    <SourceSubject
      key={`${subject.version_id}:${subject.fragment_id}`}
      versionId={subject.version_id}
      fragmentId={subject.fragment_id}
      runId={subject.analysis_id}
    />
  ) : (
    <p role="alert">Привязка источника недоступна.</p>
  );
}
