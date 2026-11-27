import { useState } from 'react';
import {
  answerQuestion,
  answerSchema,
  recoverDecision,
  type AnswerCommand,
  type Decision,
  type Question,
} from '../../shared/api/clarifications';
import { useInvalidateClarifications } from '../../shared/api/use-clarifications';
import { Button } from '../../shared/ui/button';
import { savedValue } from './saved-command';
import { usePersistedCommand } from './use-persisted-command';
import { draftIsCurrent, draftSchema, pinDraft, type AnswerDraft } from './answer-draft';
import { StaleDraft } from './stale-draft';
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
  const [draft, setDraft] = useState(() => store.read() ?? pinDraft(question, sourceVersions));
  const assumption = draft.kind === 'assumption';
  const current = draftIsCurrent(draft, question, sourceVersions);
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
  function update(next: AnswerDraft) {
    setDraft(next);
    store.save(next);
  }
  const disabled = state.mutation.isPending || state.recovery.isFetching || state.recovery.isError;
  function submit() {
    if (!state.pending && !current) return;
    state.submit({
      operation_id: crypto.randomUUID(),
      expected_question_revision: draft.question_revision ?? question.revision,
      source_versions: draft.source_versions,
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
      noValidate={state.pending !== null}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {!current && (
        <StaleDraft
          draft={draft}
          question={question}
          disabled={disabled || state.pending !== null}
          transfer={() => update(pinDraft(question, sourceVersions, draft))}
        />
      )}
      <AnswerFields draft={draft} update={update} disabled={!current} />
      <Button disabled={disabled || (!current && state.pending === null)}>
        {state.pending
          ? 'Повторить сохранённый ответ'
          : assumption
            ? 'Принять допущение'
            : 'Сохранить ответ'}
      </Button>
      <AnswerStatus state={state} recoveredEarlierRevision={recoveredEarlierRevision} />
    </form>
  );
}

function AnswerFields({
  draft,
  update,
  disabled,
}: {
  draft: AnswerDraft;
  update: (draft: AnswerDraft) => void;
  disabled: boolean;
}) {
  return (
    <fieldset disabled={disabled} className="answer-fields">
      <label className="field-label">
        Ответ архитектора
        <textarea
          value={draft.text}
          required
          maxLength={8000}
          onChange={(event) => update({ ...draft, text: event.target.value })}
        />
      </label>
      <label className="field-label">
        Основание ответа
        <textarea
          value={draft.basis}
          required
          maxLength={8000}
          onChange={(event) => update({ ...draft, basis: event.target.value })}
        />
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={draft.kind === 'assumption'}
          onChange={(event) =>
            update({ ...draft, kind: event.target.checked ? 'assumption' : 'answer' })
          }
        />
        Принять как допущение
      </label>
      {draft.kind === 'assumption' &&
        Object.entries(assumptionLabels).map(([field, label]) => (
          <label className="field-label" key={field}>
            {label}
            <textarea
              required
              value={draft[field as keyof typeof assumptionLabels]}
              onChange={(event) => update({ ...draft, [field]: event.target.value })}
            />
          </label>
        ))}
    </fieldset>
  );
}

function AnswerStatus({
  state,
  recoveredEarlierRevision,
}: {
  state: ReturnType<typeof usePersistedCommand<AnswerCommand, Decision>>;
  recoveredEarlierRevision: boolean;
}) {
  return (
    <>
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
    </>
  );
}
