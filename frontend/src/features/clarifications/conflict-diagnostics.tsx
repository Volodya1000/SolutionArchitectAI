import type { ClarificationView } from '../../shared/api/clarifications';
import { PinnedSource } from './discussion-subject';

const statuses = {
  candidate: 'Недостаточно оснований',
  confirmed: 'Обязательное противоречие подтверждено',
  refuted: 'Противоречие опровергнуто источником',
};

export function ConflictDiagnostics({ view }: { view: ClarificationView }) {
  if (view.conflict_assessments.length === 0) return null;
  return (
    <details>
      <summary>Перепроверка противоречий: {view.conflict_assessments.length}</summary>
      {view.conflict_assessments.map((assessment) => (
        <section className="surface-card" key={assessment.requirement_id}>
          <h3>{statuses[assessment.status]}</h3>
          <p>{assessment.reason}</p>
          {assessment.sources.map((source, index) => (
            <PinnedSource
              key={`${source.fragment_id}:${index}`}
              source={source}
              runId={view.run_id}
            />
          ))}
        </section>
      ))}
    </details>
  );
}
