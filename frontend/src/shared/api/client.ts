import { z } from 'zod';
import {
  zTheme,
  zRunView,
  zChatSnapshot,
  zMessageView,
  zApiFailure,
  zApiValidationFailure,
} from './generated/zod.gen';
import { InputValidationError, MESSAGE_LIMIT_HINT } from './validation';
import { ApiError } from './api-error';

export const scopeKey = [
  'workspace',
  'local',
  'task',
  '10000000-0000-4000-8000-000000000002',
] as const;
export {
  zTheme as themeSchema,
  zPreferencesOutput as preferencesSchema,
  zModelStatus as modelStatusSchema,
  zChatView as chatSchema,
  zMessageView as messageSchema,
  zRunView as runSchema,
  zChatSnapshot as snapshotSchema,
  zRunSnapshotEvent as envelopeSchema,
} from './generated/zod.gen';
export type Theme = z.infer<typeof zTheme>;
export type Run = z.infer<typeof zRunView>;
export type Snapshot = z.infer<typeof zChatSnapshot>;
export type Message = z.infer<typeof zMessageView>;
const terminalStatuses: ReadonlySet<Run['status']> = new Set(['completed', 'failed', 'cancelled']);
export const terminal = (run: Run) => terminalStatuses.has(run.status);

export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const response = await sendRequest(path, init);
  if (!response.ok) {
    if (response.status === 422) throw await validationError(response);
    const body: unknown = await response.json().catch(() => null);
    const error = zApiFailure.safeParse(body);
    throw new ApiError(
      response.status,
      error.success ? error.data.code : null,
      'Не удалось выполнить запрос. Проверьте подключение и повторите.',
    );
  }
  const data: unknown = await response.json();
  return schema.parse(data);
}

async function validationError(response: Response): Promise<InputValidationError> {
  const body: unknown = await response.json().catch(() => null);
  const result = zApiValidationFailure.safeParse(body);
  const tooLong =
    result.success &&
    result.data.detail.some(
      (error) => error.loc.includes('content') && error.type === 'string_too_long',
    );
  return new InputValidationError(
    tooLong
      ? MESSAGE_LIMIT_HINT
      : 'Проверьте введённые данные. Сообщение должно содержать текст. ' + MESSAGE_LIMIT_HINT,
  );
}

export async function sendRequest(path: string, init?: RequestInit): Promise<Response> {
  try {
    const headers = new Headers(init?.headers);
    if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    return await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new Error('Не удалось соединиться с приложением. Проверьте подключение и повторите.');
  }
}
