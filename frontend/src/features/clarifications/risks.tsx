import { Link } from 'react-router';
import { type ClarificationView } from '../../shared/api/clarifications';

const statuses = { open: 'Открыт', closed: 'Закрыт', realized: 'Реализовался' } as const;

export function ClarificationRisks({
  view,
  tabbed = false,
}: {
  view: ClarificationView;
  tabbed?: boolean;
}) {
  if (view.risks.length === 0) return <p className="notice">Рисков допущений нет.</p>;
  return (
    <section className="clarifications" aria-label="Риски A-07">
      <h2>Риски A-07</h2>
      {view.risks.map((risk) => (
        <article
          className="surface-card clarification-card"
          key={risk.id}
          id={`risk-${risk.id}`}
          tabIndex={-1}
        >
          <h3>Риск допущения</h3>
          <dl className="metadata-grid">
            <dt>Последствия</dt>
            <dd>{risk.consequences}</dd>
            <dt>Снижение</dt>
            <dd>{risk.mitigation}</dd>
            <dt>Статус</dt>
            <dd>{statuses[risk.status]}</dd>
            {risk.resolution_reason && (
              <>
                <dt>Причина решения</dt>
                <dd>{risk.resolution_reason}</dd>
              </>
            )}
          </dl>
          <Link
            className="text-link"
            to={`${tabbed ? `/requirements?run=${encodeURIComponent(view.run_id)}&tab=clarifications` : ''}#decision-${risk.decision_id}`}
          >
            Допущение A-01
          </Link>
        </article>
      ))}
    </section>
  );
}
