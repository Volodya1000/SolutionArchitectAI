import { createContext, useContext } from 'react';
import type { Theme } from '../api/client';

export const ThemeContext = createContext<{
  theme: Theme;
  setTheme: (theme: Theme) => void;
  savingFailed: boolean;
} | null>(null);
export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error('ThemeProvider is required');
  return value;
}
