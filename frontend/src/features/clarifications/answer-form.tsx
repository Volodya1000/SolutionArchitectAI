import { useState } from 'react';
import { z } from 'zod';
import {
  answerQuestion,
  answerSchema,
  recoverDecision,
  type Question,
} from '../../shared/api/clarifications';
import { useInvalidateClarifications } from '../../shared/api/use-clarifications';
import { Button } from '../../shared/ui/button';
import { savedValue } from './saved-command';
import { usePersistedCommand } from './use-persisted-command';

const draftSchema = z.object({
  text: z.string(),
  basis: z.string(),
  responsible: z.string(),
  verification_condition: z.string(),
  consequences: z.string(),
  mitigation: z.string(),
});
const emptyDraft = {
  text: '',
  basis: '',
  responsible: '',
  verification_condition: '',
  consequences: '',
  mitigation: '',
};
const assumptionLabels = {
  responsible: 'Ответственный',
  verification_condition: 'Условие проверки',
  consequences: 'Последствия',
  mitigation: 'Способ снижения риска',
} as const;
export function AnswerForm({
  runId,
  question,
  sourceVersions,
}: {
  runId: string;
  question: Question;
  sourceVersions: { version_id: string; sha256: string }[];
}) {
  const store = savedValue(`draft:${runId}:${question.id}`, draftSchema);
  const [draft, setDraft] = useState(() => store.read() ?? emptyDraft);
  const [assumption, setAssumption] = useState(false);
  const [recoveredEarlierRevision, setRecoveredEarlierRevision] = useState(false);
  const invalidate = useInvalidateClarifications();
  const state = usePersistedCommand({
    key: `answer:${runId}:${question.id}`,
    schema: answerSchema,
    recover: recoverDecision,
    execute: (command) => answerQuestion(runId, question.id, command),
    onSuccess: async (result) => {
      const earlierRevision = result.question_revision !== question.revision;
      setRecoveredEarlierRevision(earlierRevision);
      if (!earlierRevision) store.clear();
      await invalidate();
    },
    onConflict: invalidate,
  });
  function update(field: keyof typeof draft, value: string) {
    const next = { ...draft, [field]: value };
    setDraft(next);
    store.save(next);
  }
  const disabled = state.mutation.isPending || state.recovery.isFetching || state.recovery.isError;
  function submit() {
    state.submit({
      operation_id: crypto.randomUUID(),
      expected_question_revision: question.revision,
      source_versions: sourceVersions,
      kind: assumption ? 'assumption' : 'answer',
      text: draft.text.trim(),
      basis: draft.basis.trim(),
      assumption: assumption
        ? {
            responsible: draft.responsible,
            verification_condition: draft.verification_condition,
            consequences: draft.consequences,
            mitigation: draft.mitigation,
          }
        : null,
    });
  }
  return (
    <form
      className="clarification-form"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label className="field-label">
        Ответ архитектора
        <textarea
          value={draft.text}
          required
          maxLength={8000}
          onChange={(event) => update('text', event.target.value)}
        />
      </label>
      <label className="field-label">
        Основание ответа
        <textarea
          value={draft.basis}
          required
          maxLength={8000}
          onChange={(event) => update('basis', event.target.value)}
        />
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={assumption}
          onChange={(event) => setAssumption(event.target.checked)}
        />
        Принять как допущение
      </label>
      {assumption &&
        Object.entries(assumptionLabels).map(([field, label]) => (
          <label className="field-label" key={field}>
            {label}
            <textarea
              required
              value={draft[field as keyof typeof assumptionLabels]}
              onChange={(event) =>
                update(field as keyof typeof assumptionLabels, event.target.value)
              }
            />
          </label>
        ))}
      <Button disabled={disabled}>
        {state.pending
          ? 'Повторить сохранённый ответ'
          : assumption
            ? 'Принять допущение'
            : 'Сохранить ответ'}
      </Button>
      {state.pending && (
        <p className="notice">
          Сохраняется исходная команда и её ревизия. Текущий ввод не меняет повтор.
        </p>
      )}
      {recoveredEarlierRevision && (
        <p className="notice" role="status">
          Восстановлено решение прежней ревизии. Ответ для текущей ревизии ещё не сохранён.
        </p>
      )}
      {state.mutation.isError && (
        <p className="notice error-text" role="alert">
          {state.mutation.error.message}
        </p>
      )}
      {state.recovery.isError && (
        <p role="alert">
          Проверка результата недоступна.{' '}
          <Button
            type="button"
            onClick={() => {
              void state.recovery.refetch();
            }}
          >
            Проверить операцию
          </Button>
        </p>
      )}
    </form>
  );
}
