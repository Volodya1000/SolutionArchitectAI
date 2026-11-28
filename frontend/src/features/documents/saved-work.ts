import { z } from 'zod';
import { scopeKey } from '../../shared/api/client';
import { sessionStore } from '../../shared/ui/session-storage';

const prefix = `${scopeKey.join(':')}:documents`;
const draftSchema = z.object({ versionIds: z.array(z.string()), scope: z.string() });
const extractionCommandSchema = z.object({
  operation_id: z.uuid(),
  version_ids: z.array(z.string()),
  analysis_scope: z.string(),
  answer_history_mode: z.enum(['reuse', 'new']).optional(),
  answer_history_id: z.string().nullable().optional(),
});
const uploadDescriptionSchema = z.object({
  operationId: z.uuid(),
  fileId: z.string().nullable(),
  name: z.string(),
  size: z.number(),
  sha256: z.string(),
});
export type UploadDescription = z.infer<typeof uploadDescriptionSchema>;

function readSaved<T>(key: string, schema: z.ZodType<T>): T | null {
  try {
    const value: unknown = JSON.parse(sessionStore.get(key) ?? 'null');
    return schema.safeParse(value).data ?? null;
  } catch {
    return null;
  }
}

export const analysisDraft = {
  read: () => readSaved(`${prefix}:draft`, draftSchema) ?? { versionIds: [], scope: '' },
  save: (draft: z.infer<typeof draftSchema>) =>
    sessionStore.set(`${prefix}:draft`, JSON.stringify(draft)),
};
export const extractionCommand = {
  read: () => readSaved(`${prefix}:analysis`, extractionCommandSchema),
  save: (command: z.infer<typeof extractionCommandSchema>) =>
    sessionStore.set(`${prefix}:analysis`, JSON.stringify(command)),
  clear: (operationId: string) => {
    if (extractionCommand.read()?.operation_id === operationId)
      sessionStore.remove(`${prefix}:analysis`);
  },
};
export const uploadDescription = {
  read: (fileId: string | null) =>
    readSaved(`${prefix}:upload:${fileId ?? 'new'}`, uploadDescriptionSchema),
  save: (command: UploadDescription) =>
    sessionStore.set(`${prefix}:upload:${command.fileId ?? 'new'}`, JSON.stringify(command)),
  clear: (command: UploadDescription) => {
    if (uploadDescription.read(command.fileId)?.operationId === command.operationId)
      sessionStore.remove(`${prefix}:upload:${command.fileId ?? 'new'}`);
  },
};

export async function describeUpload(
  file: File,
  fileId: string | null,
): Promise<UploadDescription> {
  const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      reader.result instanceof ArrayBuffer
        ? resolve(reader.result)
        : reject(new Error('Не удалось прочитать файл.'));
    reader.onerror = () => reject(new Error('Не удалось прочитать файл.'));
    reader.readAsArrayBuffer(file);
  });
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  const sha256 = [...new Uint8Array(hash)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
  return { fileId, operationId: crypto.randomUUID(), name: file.name, size: file.size, sha256 };
}

export function sameUpload(left: UploadDescription, right: UploadDescription): boolean {
  return (
    left.fileId === right.fileId &&
    left.name === right.name &&
    left.size === right.size &&
    left.sha256 === right.sha256
  );
}
