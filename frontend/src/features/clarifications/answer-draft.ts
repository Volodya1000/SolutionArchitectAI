import { z } from 'zod';
import { answerSchema, type Question } from '../../shared/api/clarifications';

export const draftSchema = z.object({
  text: z.string(),
  basis: z.string(),
  responsible: z.string(),
  verification_condition: z.string(),
  consequences: z.string(),
  mitigation: z.string(),
  kind: z.enum(['answer', 'assumption']).default('answer'),
  question_revision: z.number().nullable().default(null),
  question_text: z.string().default(''),
  question_basis: z.string().default(''),
  source_versions: answerSchema.shape.source_versions.default([]),
});
export type AnswerDraft = z.infer<typeof draftSchema>;
export type SourceVersions = AnswerDraft['source_versions'];

export function pinDraft(
  question: Question,
  sourceVersions: SourceVersions,
  draft: AnswerDraft = draftSchema.parse({
    text: '',
    basis: '',
    responsible: '',
    verification_condition: '',
    consequences: '',
    mitigation: '',
  }),
): AnswerDraft {
  return {
    ...draft,
    question_revision: question.revision,
    question_text: question.text,
    question_basis: question.basis,
    source_versions: sourceVersions,
  };
}

export function draftIsCurrent(
  draft: AnswerDraft,
  question: Question,
  sourceVersions: SourceVersions,
) {
  const canonical = (sources: SourceVersions) =>
    JSON.stringify(
      sources
        .map(({ version_id, sha256 }) => ({ version_id, sha256 }))
        .sort((first, second) => first.version_id.localeCompare(second.version_id)),
    );
  return (
    draft.question_revision === question.revision &&
    draft.question_text === question.text &&
    draft.question_basis === question.basis &&
    canonical(draft.source_versions) === canonical(sourceVersions)
  );
}
