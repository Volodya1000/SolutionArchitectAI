import { Link } from 'react-router';
import type { Decision, Question } from '../../shared/api/clarifications';

export function RequirementClarifications({
  runId,
  requirementId,
  originalText,
  questions,
  decisions,
}: {
  runId: string;
  requirementId: string;
  originalText: string;
  questions: Question[];
  decisions: Decision[];
}) {
  const related = questions.filter((question) => question.requirement_ids.includes(requirementId));
  const conditions = decisions.filter(
    (decision) =>
      (decision.requirement_ids.includes(requirementId) ||
        related.some((question) => question.id === decision.question_id)) &&
      decision.resolution !== 'rejected',
  );
  return (
    <>
      {conditions.length > 0 && (
        <p>
          <strong>Исходная формулировка:</strong> {originalText}
        </p>
      )}
      {related.map((question) => (
        <p key={question.id}>
          <Link
            className="text-link"
            to={`/requirements?run=${encodeURIComponent(runId)}&tab=clarifications&question=${encodeURIComponent(question.id)}&requirement=${encodeURIComponent(requirementId)}#question-${question.id}`}
          >
            Открыть вопрос: {question.text}
          </Link>
        </p>
      ))}
      {conditions.map((decision) => (
        <div className="human-decision" key={decision.decision_id}>
          <strong>Добавленное условие архитектора</strong>
          <p>{decision.text}</p>
          <p>
            Автор: {decision.author} ·{' '}
            <time dateTime={decision.created_at}>
              {new Date(decision.created_at).toLocaleString('ru-RU')}
            </time>
          </p>
          <p>Основание: {decision.basis}</p>
          {decision.run_id !== runId && (
            <p className="notice">
              Происхождение:{' '}
              <Link
                className="text-link"
                to={`/requirements?run=${encodeURIComponent(decision.run_id)}&tab=clarifications#decision-${decision.decision_id}`}
              >
                Решение из другого анализа
              </Link>
            </p>
          )}
        </div>
      ))}
    </>
  );
}
