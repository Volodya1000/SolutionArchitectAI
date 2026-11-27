const memory = new Map<string, string>();
const fallbackKeys = new Set<string>();

export const sessionStore = {
  get(key: string): string | null {
    if (fallbackKeys.has(key)) return memory.get(key) ?? null;
    try {
      const value = sessionStorage.getItem(key);
      if (value === null) memory.delete(key);
      else memory.set(key, value);
      return value;
    } catch {
      return memory.get(key) ?? null;
    }
  },
  set(key: string, value: string): void {
    memory.set(key, value);
    try {
      sessionStorage.setItem(key, value);
      fallbackKeys.delete(key);
    } catch {
      fallbackKeys.add(key);
    }
  },
  remove(key: string): void {
    memory.delete(key);
    try {
      sessionStorage.removeItem(key);
      fallbackKeys.delete(key);
    } catch {
      fallbackKeys.add(key);
    }
  },
  clear(): void {
    memory.clear();
    fallbackKeys.clear();
    try {
      sessionStorage.clear();
    } catch {
      // In-memory drafts remain usable when browser storage is unavailable.
    }
  },
};
