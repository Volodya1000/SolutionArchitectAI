import { z } from 'zod';
import { requirementSchema, sourceSchema } from './extractions';
import { resourceRequest } from './resource-client';
import { ApiError } from './api-error';

const assumptionSchema = z.object({
  responsible: z.string(),
  verification_condition: z.string(),
  consequences: z.string(),
  mitigation: z.string(),
});
export const answerSchema = z.object({
  operation_id: z.string(),
  expected_question_revision: z.number(),
  source_versions: z.array(z.object({ version_id: z.string(), sha256: z.string() })),
  kind: z.enum(['answer', 'assumption']),
  text: z.string(),
  basis: z.string(),
  assumption: assumptionSchema.nullable(),
});
export type AnswerCommand = z.infer<typeof answerSchema>;
export const questionSchema = z.object({
  id: z.string(),
  gap_key: z.string(),
  revision: z.number(),
  text: z.string(),
  basis: z.string(),
  dependent_decision: z.string(),
  blocking: z.boolean(),
  requirement_ids: z.array(z.string()),
  sources: z.array(sourceSchema),
  status: z.enum(['open', 'answered', 'assumed']),
  previous_basis: z.string().nullable().default(null),
  previous_sources: z.array(sourceSchema).default([]),
  mandatory_conflict: z.string().nullable().default(null),
});
export type Question = z.infer<typeof questionSchema>;
export function questionBlocksCompletion(question: Question): boolean {
  return (
    (question.blocking && question.status === 'open') ||
    (question.mandatory_conflict !== null &&
      (question.status === 'open' || question.status === 'assumed'))
  );
}
export const decisionSchema = z.object({
  operation_id: z.string(),
  run_id: z.string(),
  question_id: z.string(),
  question_revision: z.number(),
  decision_id: z.string(),
  kind: z.enum(['answer', 'assumption']),
  text: z.string(),
  basis: z.string(),
  author_id: z.string(),
  author: z.string(),
  created_at: z.string(),
  requirement_ids: z.array(z.string()),
  assumption: assumptionSchema.nullable(),
  risk_id: z.string().nullable(),
  resolution: z.enum(['pending', 'confirmed', 'rejected']),
  resolution_reason: z.string().nullable(),
  resolved_by: z.string().nullable().optional(),
  resolved_author: z.string().nullable().optional(),
  resolved_at: z.string().nullable().optional(),
  revision: z.number(),
});
export type Decision = z.infer<typeof decisionSchema>;
const riskSchema = z.object({
  id: z.string(),
  decision_id: z.string(),
  consequences: z.string(),
  mitigation: z.string(),
  status: z.enum(['open', 'closed', 'realized']),
  resolution_reason: z.string().nullable().default(null),
});
const reviewCoverageSchema = z.object({
  total_fragments: z.number(),
  reviewed_fragments: z.number(),
  total_history: z.number(),
  reviewed_history: z.number(),
  model_requests: z.number(),
  complete: z.boolean(),
  unreviewed_fragment_ids: z.array(z.string()),
  unreviewed_question_ids: z.array(z.string()),
});
export type ClarificationReviewCoverage = z.infer<typeof reviewCoverageSchema>;
export const clarificationSchema = z.object({
  run_id: z.string(),
  history_id: z.string(),
  cycle: z.number(),
  initialized: z.boolean(),
  resume_pending: z.boolean(),
  metadata: z
    .object({ coverage: reviewCoverageSchema.nullable().default(null) })
    .nullable()
    .default(null),
  questions: z.array(questionSchema),
  decisions: z.array(decisionSchema),
  risks: z.array(riskSchema),
  requirements: z.array(requirementSchema),
  completed_cycles: z.array(
    z.object({ cycle: z.number(), completed_at: z.string(), decision_ids: z.array(z.string()) }),
  ),
});
export const readClarifications = (id: string) =>
  resourceRequest(`/extractions/${encodeURIComponent(id)}/clarifications`, clarificationSchema);
export type ClarificationView = z.infer<typeof clarificationSchema>;
export const answerQuestion = (run: string, question: string, command: AnswerCommand) =>
  resourceRequest(
    `/extractions/${encodeURIComponent(run)}/questions/${encodeURIComponent(question)}/answers`,
    decisionSchema,
    { method: 'POST', body: JSON.stringify(command) },
  );
export async function recoverDecision(id: string) {
  try {
    return await resourceRequest(
      `/clarification-operations/${encodeURIComponent(id)}`,
      decisionSchema,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
export const resolutionSchema = z.object({
  operation_id: z.string(),
  expected_revision: z.number(),
  resolution: z.enum(['confirm', 'reject']),
  reason: z.string(),
});
export type ResolutionCommand = z.infer<typeof resolutionSchema>;
export const resolveAssumption = (id: string, command: ResolutionCommand) =>
  resourceRequest(`/assumptions/${encodeURIComponent(id)}/resolve`, decisionSchema, {
    method: 'POST',
    body: JSON.stringify(command),
  });
