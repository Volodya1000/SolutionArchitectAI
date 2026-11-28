import { z } from 'zod';
import {
  zRequirementCategory,
  zSourceRef,
  zRequirementView,
  zExtractionView,
  zExtractionSummary,
  zExtractionHistory,
  zExtractionStart,
  zExtractionMatches,
} from './generated/zod.gen';
import { resourceRequest } from './resource-client';
import { ApiError } from './api-error';
export const categorySchema = zRequirementCategory;
export const sourceSchema = zSourceRef;
export const requirementSchema = zRequirementView;
export const extractionSchema = zExtractionView;
export const extractionSummarySchema = zExtractionSummary;
export const extractionPageSchema = zExtractionHistory;
export type Extraction = z.infer<typeof extractionSchema>;
export type ExtractionSummary = z.infer<typeof extractionSummarySchema>;
export type ExtractionPage = z.infer<typeof extractionPageSchema>;
export type Requirement = z.infer<typeof requirementSchema>;
export type SourceRef = z.infer<typeof sourceSchema>;
export type Category = z.infer<typeof categorySchema>;
export type ExtractionCommand = z.input<typeof zExtractionStart> &
  Pick<z.output<typeof zExtractionStart>, 'analysis_scope'>;
export const categories: Readonly<Record<Category, string>> = {
  functional: 'Функциональные',
  non_functional: 'Нефункциональные',
  business_goal: 'Бизнес-цели',
  system_boundary: 'Границы системы',
  stakeholder: 'Участники и роли',
  data: 'Требования к данным',
  constraint: 'Ограничения',
  gap: 'Информационные пробелы',
  contradiction: 'Противоречия',
};
export const extractionHistory = (offset: number) =>
  resourceRequest(`/extractions/history?limit=50&offset=${offset}`, extractionPageSchema);
export const readExtractionStatus = (id: string) =>
  resourceRequest(`/extractions/${encodeURIComponent(id)}/status`, extractionSummarySchema);
export const matchingExtractions = (
  selected: ReadonlySet<string>,
  scope: string,
  newHistory = false,
  historyId: string | null = null,
) => {
  const query = new URLSearchParams({
    analysis_scope: scope.trim(),
    answer_history_mode: newHistory ? 'new' : 'reuse',
  });
  if (historyId && !newHistory) query.set('answer_history_id', historyId);
  for (const id of [...selected].sort()) query.append('version_ids', id);
  return resourceRequest(`/extractions/matching?${query.toString()}`, zExtractionMatches);
};
export const readExtraction = (id: string) =>
  resourceRequest(`/extractions/${encodeURIComponent(id)}`, extractionSchema);
export async function readExtractionOperation(operationId: string) {
  try {
    return await resourceRequest(
      `/extraction-operations/${encodeURIComponent(operationId)}`,
      extractionSchema,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
export const startExtraction = (command: ExtractionCommand) =>
  resourceRequest('/extractions', extractionSchema, {
    method: 'POST',
    body: JSON.stringify(command),
  });
export const cancelExtraction = (id: string) =>
  resourceRequest(`/extractions/${encodeURIComponent(id)}/cancel`, extractionSchema, {
    method: 'POST',
  });
export function extractionActive(run: Pick<ExtractionSummary, 'status'>): boolean {
  return run.status === 'queued' || run.status === 'running' || run.status === 'cancelling';
}
