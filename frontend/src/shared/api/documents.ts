import { z } from 'zod';
import {
  zDocumentVersionView,
  zDocumentView,
  zSourceLocator,
  zDocumentFragment,
  zParsedDocument,
  zUploadOperationView,
} from './generated/zod.gen';
import type { LocatorView } from './generated/types.gen';
import { resourceRequest } from './resource-client';
import { ApiError } from './api-error';

export const versionSchema = zDocumentVersionView;
export const documentSchema = zDocumentView;
export const locatorSchema = zSourceLocator;
export const fragmentSchema = zDocumentFragment;
export const parsedSchema = zParsedDocument.transform((data) => ({
  ...data,
  warnings: data.warnings ?? [],
}));
export type Document = z.infer<typeof documentSchema>;
export type DocumentVersion = z.infer<typeof versionSchema>;
export type Locator = z.infer<typeof locatorSchema>;
export type ParsedDocument = z.infer<typeof parsedSchema>;
export type UploadCommand = { file: File; fileId: string | null; operationId: string };

const uploadOperationSchema = zUploadOperationView;
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

const locatorLabels: Readonly<Record<string, string>> = {
  lines: 'Строки',
  page: 'Страница',
  paragraph: 'Абзацы',
  table_cell: 'Ячейка таблицы',
};
export function locatorText(locator: Locator | LocatorView): string {
  const label =
    locator.kind === 'lines' && locator.start === locator.end
      ? 'Строка'
      : (locatorLabels[locator.kind] ?? locator.kind);
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
