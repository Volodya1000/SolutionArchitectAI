import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { scopeKey } from '../../shared/api/client';
import { readDiscussion, type DiscussionBinding } from '../../shared/api/discussions';
import { QueryError } from '../../shared/ui/query-error';
import { Clarifications } from './clarifications';
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
        <p className="notice">Закреплённые версии: {subject.version_ids.join(', ')}</p>
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
          <BoundSubject subject={subject} />
          {subject.analysis_id && (
            <Clarifications
              key={subject.analysis_id}
              runId={subject.analysis_id}
              {...(subject.requirement_id ? { requirementId: subject.requirement_id } : {})}
            />
          )}
        </div>
      </details>
    </aside>
  );
}

function BoundSubject({ subject }: { subject: DiscussionBinding }) {
  if (subject.kind === 'requirement')
    return subject.analysis_id && subject.requirement_id ? (
      <RequirementSubject
        key={`${subject.analysis_id}:${subject.requirement_id}`}
        runId={subject.analysis_id}
        requirementId={subject.requirement_id}
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
