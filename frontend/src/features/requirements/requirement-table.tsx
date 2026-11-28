import { categories, type Requirement } from '../../shared/api/extractions';
import { Evidence } from './evidence';
import { DiscussButton } from '../clarifications';
import { useSearchParams } from 'react-router';
import { useEffect } from 'react';
import type { Decision, Question } from '../../shared/api/clarifications';
import { RequirementClarifications } from './requirement-clarifications';

export function RequirementTable({
  requirements,
  runId,
  questions = [],
  decisions = [],
}: {
  requirements: Requirement[];
  runId: string;
  questions?: Question[];
  decisions?: Decision[];
}) {
  const [search] = useSearchParams();
  const selectedId = search.get('requirement');
  useEffect(() => {
    const row = selectedId ? document.getElementById(`requirement-${selectedId}`) : null;
    row?.scrollIntoView?.({ block: 'center' });
    row?.focus();
  }, [selectedId, requirements]);
  if (requirements.length === 0)
    return <p className="notice">В выбранной категории пока нет кандидатов требований.</p>;
  return (
    <div className="table-scroll">
      <table className="workspace-table requirements-table">
        <caption className="sr-only">Кандидаты требований</caption>
        <thead>
          <tr>
            <th>Категория</th>
            <th>Требование</th>
            <th>Происхождение</th>
          </tr>
        </thead>
        <tbody>
          {requirements.map((requirement) => (
            <tr
              key={requirement.id}
              id={`requirement-${requirement.id}`}
              aria-selected={search.get('requirement') === requirement.id}
              tabIndex={-1}
            >
              <td>
                <span className="category-label">{categories[requirement.category]}</span>
              </td>
              <td>
                <p className="requirement-text">{requirement.normalized_text}</p>
                <RequirementClarifications
                  runId={runId}
                  requirementId={requirement.id}
                  originalText={requirement.original_text}
                  questions={questions}
                  decisions={decisions}
                />
                <DiscussButton
                  subject={{ kind: 'requirement', run_id: runId, requirement_id: requirement.id }}
                />
              </td>
              <td>
                <Evidence
                  sources={requirement.sources}
                  originalText={requirement.original_text}
                  runId={runId}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
