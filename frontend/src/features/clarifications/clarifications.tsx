import { Link } from 'react-router';
import { type Question } from '../../shared/api/clarifications';
import { useClarifications } from '../../shared/api/use-clarifications';
import { QueryError } from '../../shared/ui/query-error';
import { AnswerForm } from './answer-form';
import { HumanDecision } from './decision';

export function Clarifications({
  runId,
  requirementId,
}: {
  runId: string;
  requirementId?: string;
}) {
  const query = useClarifications(runId);
  if (query.isPending) return <p role="status">Загружаем уточнения…</p>;
  if (!query.data)
    return (
      <QueryError
        error={query.error}
        retry={() => {
          void query.refetch();
        }}
      />
    );
  const view = query.data;
  const questions = view.questions.filter(
    (question) => !requirementId || question.requirement_ids.includes(requirementId),
  );
  return (
    <section className="clarifications" aria-label="Уточнения требований">
      <h2>Уточнения A-01</h2>
      <p role="status">
        Блокирующих вопросов:{' '}
        {
          view.questions.filter((question) => question.blocking && question.status === 'open')
            .length
        }
      </p>
      <p className="notice">
        История {view.history_id} · Цикл {view.cycle + 1}
        {view.resume_pending ? ' · Продолжение поставлено в очередь' : ''}
      </p>
      {query.isError && (
        <QueryError
          error={query.error}
          retry={() => {
            void query.refetch();
          }}
        />
      )}
      {questions.map((question) => (
        <section
          className="surface-card clarification-card"
          aria-label={question.text}
          key={question.id}
        >
          <QuestionDetails question={question} runId={runId} />
          {view.decisions
            .filter((decision) => decision.question_id === question.id)
            .map((decision) => (
              <HumanDecision key={decision.decision_id} decision={decision} />
            ))}
          {question.status === 'open' && (
            <AnswerForm
              question={question}
              runId={runId}
              sourceVersions={[
                ...new Map(
                  question.sources.flatMap((source) =>
                    source.version_id && source.sha256
                      ? [
                          [
                            source.version_id,
                            { version_id: source.version_id, sha256: source.sha256 },
                          ] as const,
                        ]
                      : [],
                  ),
                ).values(),
              ]}
            />
          )}
        </section>
      ))}
      {view.risks.length > 0 && (
        <section className="surface-card" aria-label="Риски A-07">
          <h2>Риски A-07</h2>
          {view.risks.map((risk) => (
            <article key={risk.id} id={`risk-${risk.id}`}>
              <h3>Риск допущения</h3>
              <p>{risk.consequences}</p>
              <p>Снижение: {risk.mitigation}</p>
              <p>
                Статус:{' '}
                {risk.status === 'open'
                  ? 'Открыт'
                  : risk.status === 'closed'
                    ? 'Закрыт'
                    : 'Реализовался'}
              </p>
              {risk.resolution_reason && <p>{risk.resolution_reason}</p>}
              <a className="text-link" href={`#decision-${risk.decision_id}`}>
                Допущение A-01
              </a>
            </article>
          ))}
        </section>
      )}
      {view.completed_cycles.length > 0 && (
        <details>
          <summary>Завершённые циклы: {view.completed_cycles.length}</summary>
          {view.completed_cycles.map((cycle) => (
            <p key={cycle.cycle}>
              Цикл {cycle.cycle + 1} · {new Date(cycle.completed_at).toLocaleString('ru-RU')}
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
function QuestionDetails({ question, runId }: { question: Question; runId: string }) {
  return (
    <>
      <h3>{question.text}</h3>
      <p className="notice">
        Ревизия {question.revision} · {question.blocking ? 'Блокирующий' : 'Неблокирующий'} ·{' '}
        {question.status === 'open' ? 'Открыт' : 'Решение сохранено'}
      </p>
      <p>{question.basis}</p>
      {question.previous_basis && (
        <details>
          <summary>Изменение основания</summary>
          <p>Было: {question.previous_basis}</p>
          <p>Стало: {question.basis}</p>
        </details>
      )}
      <p>Зависимое решение: {question.dependent_decision}</p>
      {question.sources.map((source, index) => (
        <div key={`${source.fragment_id}:${index}`}>
          <blockquote>{source.quote}</blockquote>
          {source.version_id && (
            <Link
              className="text-link"
              to={`/documents?version=${encodeURIComponent(source.version_id)}&fragment=${encodeURIComponent(source.fragment_id)}&run=${encodeURIComponent(runId)}`}
            >
              Источник · версия {source.version_id}
            </Link>
          )}
          <p className="version-meta">SHA-256: {source.sha256}</p>
        </div>
      ))}
    </>
  );
}
