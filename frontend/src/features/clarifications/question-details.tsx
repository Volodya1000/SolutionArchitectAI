import { type Question } from '../../shared/api/clarifications';
import { PinnedSource } from './discussion-subject';
import { Link, useSearchParams } from 'react-router';

export function QuestionDetails({
  question,
  runId,
  compactSources,
}: {
  question: Question;
  runId: string;
  compactSources: boolean;
}) {
  const [search] = useSearchParams();
  const selectedRequirement = search.get('requirement');
  return (
    <>
      <h3>{question.text}</h3>
      <dl className="metadata-grid question-metadata">
        <dt>Ревизия</dt>
        <dd>{question.revision}</dd>
        <dt>Приоритет</dt>
        <dd>{question.blocking ? 'Блокирующий' : 'Неблокирующий'}</dd>
        <dt>Статус</dt>
        <dd>{question.status === 'open' ? 'Открыт' : 'Решение сохранено'}</dd>
        <dt>Зависимое решение</dt>
        <dd>{question.dependent_decision}</dd>
      </dl>
      <p>{question.basis}</p>
      {selectedRequirement && question.requirement_ids.includes(selectedRequirement) && (
        <p>
          <Link
            className="text-link"
            to={`/requirements?run=${encodeURIComponent(runId)}&tab=requirements&requirement=${encodeURIComponent(selectedRequirement)}`}
          >
            Вернуться к выбранному требованию
          </Link>
        </p>
      )}
      {question.requirement_ids.map((id, index) => (
        <p key={id}>
          <Link
            className="text-link"
            to={`/requirements?run=${encodeURIComponent(runId)}&tab=requirements&requirement=${encodeURIComponent(id)}`}
          >
            К связанному требованию {index + 1}
          </Link>
        </p>
      ))}
      {question.mandatory_conflict && (
        <p className="notice error-text" role="alert">
          {question.mandatory_conflict}
        </p>
      )}
      {(question.previous_basis || question.previous_sources.length > 0) && (
        <details>
          <summary>Изменение основания</summary>
          <p>Было: {question.previous_basis ?? 'Прежние источники'}</p>
          {question.previous_sources.map((source, index) => (
            <PinnedSource key={`${source.fragment_id}:${index}`} source={source} runId={null} />
          ))}
          <p>Стало: {question.basis}</p>
        </details>
      )}
      {question.sources.length > 0 && (
        <details open={!compactSources}>
          <summary>Источники вопроса: {question.sources.length}</summary>
          {question.sources.map((source, index) => (
            <PinnedSource key={`${source.fragment_id}:${index}`} source={source} runId={runId} />
          ))}
        </details>
      )}
    </>
  );
}
