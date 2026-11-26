import { z } from 'zod';
import { locatorSchema } from './documents';
import { resourceRequest } from './resource-client';

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
  status: z.enum(['queued', 'running', 'cancelling', 'completed', 'failed', 'cancelled']),
  progress: z.object({ completed_parts: z.number(), total_parts: z.number() }),
  error_code: z.string().nullable(),
  created_at: z.string(),
  model: z.string(),
  coverage: z.object({
    complete: z.boolean(),
    total_fragments: z.number(),
    processed_fragments: z.number(),
    warnings: z.array(z.string()).optional(),
  }),
  requirements: z.array(requirementSchema),
});
export type Extraction = z.infer<typeof extractionSchema>;
export type Requirement = z.infer<typeof requirementSchema>;
export type SourceRef = z.infer<typeof sourceSchema>;
export type Category = z.infer<typeof categorySchema>;
export type ExtractionCommand = {
  operation_id: string;
  version_ids: string[];
  analysis_scope: string;
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
export const extractionList = () => resourceRequest('/extractions', z.array(extractionSchema));
export const readExtraction = (id: string) =>
  resourceRequest(`/extractions/${encodeURIComponent(id)}`, extractionSchema);
export const startExtraction = (command: ExtractionCommand) =>
  resourceRequest('/extractions', extractionSchema, {
    method: 'POST',
    body: JSON.stringify(command),
  });
export const cancelExtraction = (id: string) =>
  resourceRequest(`/extractions/${encodeURIComponent(id)}/cancel`, extractionSchema, {
    method: 'POST',
  });
export function extractionActive(run: Extraction): boolean {
  return run.status === 'queued' || run.status === 'running' || run.status === 'cancelling';
}
