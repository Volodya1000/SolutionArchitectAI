import { z } from 'zod';
import { sessionStore } from '../../shared/ui/session-storage';

const commandSchema = z.object({ command_id: z.uuid(), content: z.string() });
export type PendingCommand = z.infer<typeof commandSchema>;

export function readPending(chatId: string): PendingCommand | null {
  try {
    const value: unknown = JSON.parse(sessionStore.get(`pending:${chatId}`) ?? 'null');
    return commandSchema.safeParse(value).data ?? null;
  } catch {
    return null;
  }
}

export function savePending(chatId: string, command: PendingCommand | null) {
  if (command) sessionStore.set(`pending:${chatId}`, JSON.stringify(command));
  else sessionStore.remove(`pending:${chatId}`);
}
