import { z } from 'zod';
import { scopeKey } from '../../shared/api/client';
import { sessionStore } from '../../shared/ui/session-storage';

export function savedValue<T>(key: string, schema: z.ZodType<T>) {
  const storageKey = `${scopeKey.join(':')}:clarifications:${key}`;
  return {
    read(): T | null {
      try {
        const value: unknown = JSON.parse(sessionStore.get(storageKey) ?? 'null');
        return schema.safeParse(value).data ?? null;
      } catch {
        return null;
      }
    },
    save(value: T) {
      sessionStore.set(storageKey, JSON.stringify(value));
    },
    clear() {
      sessionStore.remove(storageKey);
    },
  };
}
