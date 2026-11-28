import { z } from 'zod';
import {
  zAnswerClarification,
  zClarificationQuestion,
  zDecisionResult,
  zClarificationView,
  zClarificationReviewCoverage,
  zResolveAssumption,
} from './generated/zod.gen';
import { resourceRequest } from './resource-client';
import { ApiError } from './api-error';
export const answerSchema = zAnswerClarification;
export type AnswerCommand = z.input<typeof answerSchema>;
export const questionSchema = zClarificationQuestion;
export type Question = z.infer<typeof questionSchema>;
export const decisionSchema = zDecisionResult;
export type Decision = z.infer<typeof decisionSchema>;
export const clarificationSchema = zClarificationView;
export type ClarificationReviewCoverage = z.infer<typeof zClarificationReviewCoverage>;
export function questionBlocksCompletion(question: Question): boolean {
  return (
    (question.blocking && question.status === 'open') ||
    (question.mandatory_conflict !== null &&
      (question.status === 'open' || question.status === 'assumed'))
  );
}
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
export const resolutionSchema = zResolveAssumption;
export type ResolutionCommand = z.infer<typeof resolutionSchema>;
export const resolveAssumption = (id: string, command: ResolutionCommand) =>
  resourceRequest(`/assumptions/${encodeURIComponent(id)}/resolve`, decisionSchema, {
    method: 'POST',
    body: JSON.stringify(command),
  });
