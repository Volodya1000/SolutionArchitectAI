import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { preferencesSchema, request, scopeKey, themeSchema, type Theme } from '../api/client';
import { ThemeContext } from './theme-context';

function localTheme(): Theme {
  try {
    return themeSchema.catch('system').parse(localStorage.getItem('saa-theme'));
  } catch {
    return 'system';
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [initial] = useState(localTheme);
  const [selection, select] = useState<Theme | null>(null);
  const [systemDark, setSystemDark] = useState(
    () => matchMedia('(prefers-color-scheme: dark)').matches,
  );
  const preferences = useQuery({
    queryKey: [...scopeKey, 'preferences'],
    queryFn: () => request('/preferences', preferencesSchema),
  });
  const save = useMutation({
    mutationFn: (theme: Theme) =>
      request('/preferences', preferencesSchema, {
        method: 'PUT',
        body: JSON.stringify({ theme }),
      }),
    onSuccess: (value) => queryClient.setQueryData([...scopeKey, 'preferences'], value),
  });
  const theme = selection ?? preferences.data?.theme ?? initial;
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const listener = () => setSystemDark(media.matches);
    media.addEventListener('change', listener);
    return () => media.removeEventListener('change', listener);
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle(
      'dark',
      theme === 'dark' || (theme === 'system' && systemDark),
    );
    try {
      localStorage.setItem('saa-theme', theme);
    } catch {
      /* Selection still works without storage. */
    }
  }, [theme, systemDark]);
  const setTheme = (next: Theme) => {
    select(next);
    save.mutate(next);
  };
  return (
    <ThemeContext.Provider value={{ theme, setTheme, savingFailed: save.isError }}>
      {children}
    </ThemeContext.Provider>
  );
}
