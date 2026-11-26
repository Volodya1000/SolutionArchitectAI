import { z } from 'zod';
import { InputValidationError, MESSAGE_LIMIT_HINT } from './validation';

export const scopeKey = [
  'workspace',
  'local',
  'task',
  '10000000-0000-4000-8000-000000000002',
] as const;
export const themeSchema = z.enum(['light', 'dark', 'system']);
export type Theme = z.infer<typeof themeSchema>;
export const preferencesSchema = z.object({ theme: themeSchema });
export const modelStatusSchema = z.object({ model: z.string(), available: z.boolean() });
export const chatSchema = z.object({
  id: z.string(),
  task_id: z.string(),
  title: z.string(),
  created_at: z.string(),
});
export const messageSchema = z.object({
  id: z.string(),
  role: z.enum(['user', 'assistant']),
  content: z.string(),
  position: z.number(),
  incomplete: z.boolean(),
});
export const runSchema = z.object({
  id: z.string(),
  chat_id: z.string(),
  assistant_message_id: z.string(),
  status: z.enum(['queued', 'running', 'cancelling', 'completed', 'failed', 'cancelled']),
  sequence: z.number(),
  content: z.string(),
  incomplete: z.boolean(),
  error_code: z.string().nullable(),
  model: z.string(),
});
export const snapshotSchema = z.object({
  chat: chatSchema,
  messages: z.array(messageSchema),
  runs: z.array(runSchema),
});
export const envelopeSchema = z.object({
  run_id: z.string(),
  sequence: z.number(),
  kind: z.literal('snapshot'),
  payload: runSchema,
});
export type Run = z.infer<typeof runSchema>;
export type Snapshot = z.infer<typeof snapshotSchema>;
export type Message = z.infer<typeof messageSchema>;
export const terminal = (run: Run) => ['completed', 'failed', 'cancelled'].includes(run.status);

export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const response = await sendRequest(path, init);
  if (!response.ok) {
    if (response.status === 422) throw await validationError(response);
    const message =
      response.status === 409
        ? 'В этом чате уже выполняется запрос. Обновите состояние.'
        : 'Не удалось выполнить запрос. Проверьте подключение и повторите.';
    throw new Error(message);
  }
  const data: unknown = await response.json();
  return schema.parse(data);
}

async function validationError(response: Response): Promise<InputValidationError> {
  const body: unknown = await response.json().catch(() => null);
  const result = z
    .object({
      detail: z.array(
        z.object({
          loc: z.array(z.union([z.string(), z.number()])),
          type: z.string(),
        }),
      ),
    })
    .safeParse(body);
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

async function sendRequest(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`/api${path}`, { ...init, headers: { 'Content-Type': 'application/json' } });
  } catch {
    throw new Error('Не удалось соединиться с приложением. Проверьте подключение и повторите.');
  }
}
