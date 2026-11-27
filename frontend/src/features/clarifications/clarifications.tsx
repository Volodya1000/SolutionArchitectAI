import { questionBlocksCompletion, type ClarificationView } from '../../shared/api/clarifications';
import { useClarifications } from '../../shared/api/use-clarifications';
import { QueryError } from '../../shared/ui/query-error';
import { AnswerForm } from './answer-form';
import { HumanDecision } from './decision';
import { QuestionDetails } from './question-details';
import { ClarificationRisks } from './risks';

export function Clarifications({ runId }: { runId: string }) {
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
  return (
    <>
      {query.isError && (
        <QueryError
          error={query.error}
          retry={() => {
            void query.refetch();
          }}
        />
      )}
      <ClarificationContent view={query.data} />
    </>
  );
}

export function ClarificationContent({ view }: { view: ClarificationView }) {
  return (
    <>
      <ClarificationQuestions view={view} compactSources />
      <ClarificationRisks view={view} />
    </>
  );
}

export function ClarificationQuestions({
  view,
  compactSources = false,
  openOnly = false,
  tabbed = false,
}: {
  view: ClarificationView;
  compactSources?: boolean;
  openOnly?: boolean;
  tabbed?: boolean;
}) {
  const questions = view.questions.filter(
    (question) => !openOnly || questionBlocksCompletion(question),
  );
  const blockers = view.questions.filter(questionBlocksCompletion).length;
  return (
    <section className="clarifications" aria-label="Уточнения требований">
      <div className="section-heading">
        <h2>Уточнения A-01</h2>
        <span className="notice" role="status">
          Блокирующих вопросов: {blockers}
        </span>
      </div>
      <p className="notice">
        Цикл {view.cycle + 1}
        {view.resume_pending ? ' · Продолжение поставлено в очередь' : ''}
      </p>
      {questions.length === 0 && <p className="notice">Открытых вопросов нет.</p>}
      {questions.map((question) => (
        <section
          className="surface-card clarification-card"
          aria-label={question.text}
          id={`question-${question.id}`}
          tabIndex={-1}
          key={question.id}
        >
          <QuestionDetails
            question={question}
            runId={view.run_id}
            compactSources={compactSources}
          />
          {view.decisions
            .filter((decision) => decision.question_id === question.id)
            .map((decision) => (
              <HumanDecision key={decision.decision_id} decision={decision} tabbed={tabbed} />
            ))}
          {question.status === 'open' && (
            <AnswerForm
              question={question}
              runId={view.run_id}
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
      <details>
        <summary>Завершённые циклы: {view.completed_cycles.length}</summary>
        <p className="version-meta">История {view.history_id}</p>
        {view.completed_cycles.map((cycle) => (
          <p key={cycle.cycle}>
            Цикл {cycle.cycle + 1} · {new Date(cycle.completed_at).toLocaleString('ru-RU')}
          </p>
        ))}
      </details>
    </section>
  );
}
