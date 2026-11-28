import { useState } from 'react';
import { Link } from 'react-router';
import {
  recoverDecision,
  resolutionSchema,
  resolveAssumption,
  type Decision,
} from '../../shared/api/clarifications';
import { useInvalidateClarifications } from '../../shared/api/use-clarifications';
import { Button } from '../../shared/ui/button';
import { usePersistedCommand } from './use-persisted-command';
import { savedValue } from './saved-command';

export function HumanDecision({
  decision,
  tabbed = false,
  displayRunId,
}: {
  decision: Decision;
  tabbed?: boolean;
  displayRunId?: string;
}) {
  return (
    <article className="human-decision" id={`decision-${decision.decision_id}`} tabIndex={-1}>
      <strong>
        {decision.kind === 'assumption'
          ? assumptionHeadline[decision.resolution]
          : 'Добавил архитектор'}
      </strong>
      <p>{decision.text}</p>
      <dl className="metadata-grid">
        <dt>Автор</dt>
        <dd>{decision.author}</dd>
        <dt>Сохранено</dt>
        <dd>
          <time dateTime={decision.created_at}>
            {new Date(decision.created_at).toLocaleString('ru-RU')}
          </time>
        </dd>
        <dt>Основание</dt>
        <dd>{decision.basis}</dd>
        <dt>Ревизия вопроса</dt>
        <dd>{decision.question_revision}</dd>
        {decision.assumption && (
          <>
            <dt>Ответственный</dt>
            <dd>{decision.assumption.responsible}</dd>
            <dt>Условие проверки</dt>
            <dd>{decision.assumption.verification_condition}</dd>
            <dt>Статус</dt>
            <dd>{resolutionText[decision.resolution]}</dd>
            {decision.resolution_reason && (
              <>
                <dt>Причина решения</dt>
                <dd>{decision.resolution_reason}</dd>
              </>
            )}
          </>
        )}
      </dl>
      {decision.assumption && (
        <>
          <Link
            className="text-link"
            to={`${tabbed ? `/requirements?run=${encodeURIComponent(displayRunId ?? decision.run_id)}&tab=risks` : ''}#risk-${decision.risk_id ?? ''}`}
          >
            Риск A-07
          </Link>
          <ResolutionProvenance decision={decision} />
          {decision.resolution === 'pending' && <ResolveDecision decision={decision} />}
        </>
      )}
    </article>
  );
}
function ResolutionProvenance({ decision }: { decision: Decision }) {
  if (!decision.resolved_author && !decision.resolved_at && !decision.resolved_by) return null;
  return (
    <>
      <p className="notice">
        Решение: {decision.resolved_author ?? 'Архитектор'}
        {decision.resolved_at && (
          <>
            {' '}
            ·{' '}
            <time dateTime={decision.resolved_at}>
              {new Date(decision.resolved_at).toLocaleString('ru-RU')}
            </time>
          </>
        )}
      </p>
      {decision.resolved_by && (
        <details>
          <summary>Технические сведения решения</summary>
          <p className="version-meta">Автор решения: {decision.resolved_by}</p>
        </details>
      )}
    </>
  );
}
const resolutionText = {
  pending: 'Подлежит верификации',
  confirmed: 'Подтверждено',
  rejected: 'Отклонено — требуется пересмотр',
} as const;
const assumptionHeadline = {
  pending: 'Принято допущение',
  confirmed: 'Допущение подтверждено',
  rejected: 'Допущение отклонено — требуется пересмотр',
} as const;
function ResolveDecision({ decision }: { decision: Decision }) {
  const store = savedValue(
    `resolution-draft:${decision.run_id}:${decision.decision_id}`,
    resolutionSchema.omit({ operation_id: true, expected_revision: true }),
  );
  const [draft, setDraft] = useState(
    () => store.read() ?? { reason: '', resolution: 'confirm' as const },
  );
  const { reason, resolution } = draft;
  function update(next: typeof draft) {
    setDraft(next);
    store.save(next);
  }
  const invalidate = useInvalidateClarifications();
  const state = usePersistedCommand({
    key: `resolve:${decision.run_id}:${decision.decision_id}`,
    schema: resolutionSchema,
    recover: recoverDecision,
    execute: (command) => resolveAssumption(decision.decision_id, command),
    onSuccess: async () => {
      store.clear();
      await invalidate();
    },
    onConflict: invalidate,
  });
  return (
    <form
      className="clarification-form"
      onSubmit={(event) => {
        event.preventDefault();
        state.submit({
          operation_id: crypto.randomUUID(),
          expected_revision: decision.revision,
          resolution,
          reason,
        });
      }}
    >
      <label className="field-label">
        Решение по допущению
        <select
          value={resolution}
          onChange={(event) =>
            update({ ...draft, resolution: event.target.value === 'reject' ? 'reject' : 'confirm' })
          }
        >
          <option value="confirm">Подтвердить</option>
          <option value="reject">Отклонить</option>
        </select>
      </label>
      <label className="field-label">
        Причина решения
        <textarea
          required
          value={reason}
          onChange={(event) => update({ ...draft, reason: event.target.value })}
        />
      </label>
      <Button
        disabled={state.mutation.isPending || state.recovery.isFetching || state.recovery.isError}
      >
        {state.pending ? 'Повторить решение' : 'Сохранить решение'}
      </Button>
      {state.mutation.isError && <p role="alert">{state.mutation.error.message}</p>}
      {state.recovery.isError && (
        <Button
          type="button"
          onClick={() => {
            void state.recovery.refetch();
          }}
        >
          Проверить операцию
        </Button>
      )}
    </form>
  );
}
