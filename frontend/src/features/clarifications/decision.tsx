import { useState } from 'react';
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

export function HumanDecision({ decision }: { decision: Decision }) {
  return (
    <article className="human-decision" id={`decision-${decision.decision_id}`}>
      <strong>
        {decision.kind === 'assumption'
          ? assumptionHeadline[decision.resolution]
          : 'Добавил архитектор'}
      </strong>
      <p>{decision.text}</p>
      <p className="notice">
        {decision.author} · {new Date(decision.created_at).toLocaleString('ru-RU')}
      </p>
      <p>Основание: {decision.basis}</p>
      {decision.assumption && (
        <>
          <p>Ответственный: {decision.assumption.responsible}</p>
          <p>Условие проверки: {decision.assumption.verification_condition}</p>
          <a className="text-link" href={`#risk-${decision.risk_id ?? ''}`}>
            Риск A-07
          </a>
          <p>Статус: {resolutionText[decision.resolution]}</p>
          {decision.resolution_reason && <p>{decision.resolution_reason}</p>}
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
    <p className="notice">
      Решение: {decision.resolved_author ?? decision.resolved_by}
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
  );
}
const resolutionText = {
  pending: 'Подлежит верификации',
  confirmed: 'Подтверждено',
  rejected: 'Отклонено — требуется пересмотр',
} as const;
const assumptionHeadline = {
  pending: 'Подлежит верификации',
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
