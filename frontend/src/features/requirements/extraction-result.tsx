import { useState } from 'react';
import {
  categories,
  categorySchema,
  type Category,
  type Requirement,
} from '../../shared/api/extractions';
import { RequirementTable } from './requirement-table';

export function ExtractionResult({
  candidates,
  runId,
}: {
  candidates: Requirement[];
  runId: string;
}) {
  const [category, setCategory] = useState<Category | 'all'>('all');
  const requirements = candidates.filter(
    (item) => category === 'all' || item.category === category,
  );
  return (
    <>
      <div className="section-heading">
        <label className="field-label">
          Категория требований
          <select
            value={category}
            onChange={(event) =>
              setCategory(
                event.target.value === 'all' ? 'all' : categorySchema.parse(event.target.value),
              )
            }
          >
            <option value="all">Все категории</option>
            {Object.entries(categories).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <span className="notice">Кандидатов: {requirements.length}</span>
      </div>
      <RequirementTable requirements={requirements} runId={runId} />
    </>
  );
}
