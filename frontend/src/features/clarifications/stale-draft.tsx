import { type Question } from '../../shared/api/clarifications';
import { Button } from '../../shared/ui/button';
import { type AnswerDraft } from './answer-draft';

export function StaleDraft({
  draft,
  question,
  transfer,
  disabled,
}: {
  draft: AnswerDraft;
  question: Question;
  transfer: () => void;
  disabled: boolean;
}) {
  return (
    <section className="stale-draft" aria-label="Черновик прежней ревизии">
      <p role="status">
        Вопрос или источники изменились. Проверьте прежний черновик и явно перенесите его перед
        сохранением ответа на текущую ревизию.
      </p>
      <dl className="metadata-grid">
        <dt>Черновик для ревизии</dt>
        <dd>{draft.question_revision ?? 'Не закреплена'}</dd>
        <dt>Прежний вопрос</dt>
        <dd>{draft.question_text || 'Не сохранён'}</dd>
        <dt>Прежнее основание</dt>
        <dd>{draft.question_basis || 'Не сохранено'}</dd>
        <dt>Текущая ревизия</dt>
        <dd>{question.revision}</dd>
        <dt>Текущий вопрос</dt>
        <dd>{question.text}</dd>
        <dt>Текущее основание</dt>
        <dd>{question.basis}</dd>
      </dl>
      <Button type="button" variant="outline" disabled={disabled} onClick={transfer}>
        Перенести черновик в текущую ревизию
      </Button>
    </section>
  );
}
