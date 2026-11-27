import { z } from 'zod';
import { locatorSchema } from './documents';
import { resourceRequest } from './resource-client';
import { ApiError } from './api-error';

export const categorySchema = z.enum([
  'functional',
  'non_functional',
  'business_goal',
  'system_boundary',
  'stakeholder',
  'data',
  'constraint',
  'gap',
  'contradiction',
]);
export const sourceSchema = z.object({
  file_id: z.string().nullable(),
  version_id: z.string().nullable(),
  sha256: z.string().nullable(),
  fragment_id: z.string(),
  locator: locatorSchema.nullable(),
  quote: z.string(),
  status: z.enum(['verified', 'unverified']),
  reason: z.string().nullable(),
});
export const requirementSchema = z.object({
  id: z.string(),
  category: categorySchema,
  original_text: z.string(),
  normalized_text: z.string(),
  sources: z.array(sourceSchema),
  status: z.literal('needs_review'),
});
export const extractionSchema = z.object({
  id: z.string(),
  status: z.enum([
    'queued',
    'running',
    'waiting_input',
    'cancelling',
    'completed',
    'failed',
    'cancelled',
  ]),
  progress: z.object({ completed_parts: z.number(), total_parts: z.number() }),
  error_code: z.string().nullable(),
  created_at: z.string(),
  model: z.string(),
  version_ids: z.array(z.string()).default([]),
  analysis_scope: z.string().default(''),
  configuration_current: z.boolean().default(false),
  coverage: z.object({
    complete: z.boolean(),
    total_fragments: z.number(),
    processed_fragments: z.number(),
    warnings: z.array(z.string()).optional(),
  }),
  requirements: z.array(requirementSchema),
});
export type Extraction = z.infer<typeof extractionSchema>;
export const extractionSummarySchema = extractionSchema.omit({
  coverage: true,
  requirements: true,
});
export type ExtractionSummary = z.infer<typeof extractionSummarySchema>;
export const extractionPageSchema = z.object({
  items: z.array(extractionSummarySchema),
  has_more: z.boolean(),
});
export type ExtractionPage = z.infer<typeof extractionPageSchema>;
export type Requirement = z.infer<typeof requirementSchema>;
export type SourceRef = z.infer<typeof sourceSchema>;
export type Category = z.infer<typeof categorySchema>;
export type ExtractionCommand = {
  operation_id: string;
  version_ids: string[];
  analysis_scope: string;
  answer_history_mode?: 'reuse' | 'new' | undefined;
  answer_history_id?: string | null | undefined;
};

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
  return resourceRequest(
    `/extractions/matching?${query.toString()}`,
    z.object({
      active: extractionSummarySchema.nullable(),
      current_completed: extractionSummarySchema.nullable(),
      latest_completed: extractionSummarySchema.nullable(),
    }),
  );
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
