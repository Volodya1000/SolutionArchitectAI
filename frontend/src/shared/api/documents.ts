import { z } from 'zod';
import { resourceRequest } from './resource-client';
import { ApiError } from './api-error';

export const versionSchema = z.object({
  file_id: z.string(),
  version_id: z.string(),
  sha256: z.string(),
  mime_type: z.string(),
  size: z.number(),
  original_name: z.string(),
  uploaded_at: z.string(),
  task_id: z.string(),
});
export const documentSchema = z.object({
  file_id: z.string(),
  task_id: z.string(),
  name: z.string(),
  created_at: z.string(),
  latest_version: versionSchema.nullable(),
});
export const locatorSchema = z.object({
  kind: z.enum(['lines', 'page', 'paragraph', 'table_cell']),
  start: z.number(),
  end: z.number(),
  section: z.string(),
  path: z.string().default(''),
});
export const fragmentSchema = z.object({
  fragment_id: z.string(),
  text: z.string(),
  locator: locatorSchema,
});
export const parsedSchema = z.object({
  file_id: z.string(),
  version_id: z.string(),
  sha256: z.string(),
  parser_version: z.string(),
  text: z.string(),
  fragments: z.array(fragmentSchema),
  warnings: z.array(z.string()),
});
export type Document = z.infer<typeof documentSchema>;
export type DocumentVersion = z.infer<typeof versionSchema>;
export type Locator = z.infer<typeof locatorSchema>;
export type ParsedDocument = z.infer<typeof parsedSchema>;
export type UploadCommand = { file: File; fileId: string | null; operationId: string };

const uploadOperationSchema = z.object({
  operation_id: z.string(),
  stage: z.enum(['prepared', 'completed']),
  version: versionSchema,
});
export async function readUploadOperation(operationId: string) {
  try {
    return await resourceRequest(
      `/document-uploads/${encodeURIComponent(operationId)}`,
      uploadOperationSchema,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export const documentList = () => resourceRequest('/documents', z.array(documentSchema));
export const documentVersions = (fileId: string) =>
  resourceRequest(`/documents/${encodeURIComponent(fileId)}/versions`, z.array(versionSchema));
export const parsedVersion = (versionId: string) =>
  resourceRequest(`/document-versions/${encodeURIComponent(versionId)}/parsed`, parsedSchema);
export const readVersion = (versionId: string) =>
  resourceRequest(`/document-versions/${encodeURIComponent(versionId)}`, versionSchema);

const uploadTypes: Readonly<Record<string, string>> = {
  txt: 'text/plain',
  md: 'text/markdown',
  markdown: 'text/markdown',
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
};

function uploadMime(file: File): string {
  const extension = file.name.toLowerCase().split('.').at(-1) ?? '';
  return uploadTypes[extension] ?? (file.type || 'application/octet-stream');
}

export function uploadDocument(command: UploadCommand): Promise<DocumentVersion> {
  const base = command.fileId
    ? `/documents/${encodeURIComponent(command.fileId)}/versions`
    : '/documents';
  const query = new URLSearchParams({
    operation_id: command.operationId,
    filename: command.file.name,
  });
  return resourceRequest(`${base}?${query.toString()}`, versionSchema, {
    method: 'POST',
    body: command.file,
    headers: { 'Content-Type': uploadMime(command.file) },
  });
}

const locatorLabels: Readonly<Record<Locator['kind'], string>> = {
  lines: 'Строки',
  page: 'Страница',
  paragraph: 'Абзацы',
  table_cell: 'Ячейка таблицы',
};
export function locatorText(locator: Locator): string {
  const label =
    locator.kind === 'lines' && locator.start === locator.end
      ? 'Строка'
      : locatorLabels[locator.kind];
  const range =
    locator.start === locator.end ? `${locator.start}` : `${locator.start}–${locator.end}`;
  return `${label} ${range}${locator.section ? ` · ${locator.section}` : ''}${locator.path ? ` · ${locator.path}` : ''}`;
}

export function parserWarningText(warning: string): string {
  if (warning === 'pdf_layout_and_tables_require_manual_review')
    return 'PDF: порядок текста и таблицы требуют ручной проверки по оригиналу.';
  if (warning.startsWith('pdf_pages_without_text:'))
    return `В PDF есть страницы без текста: ${warning.slice('pdf_pages_without_text:'.length)}. Покрытие исходного документа неполное.`;
  return warning;
}
