import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, beforeAll, expect, it, vi } from 'vitest';
import { themeSchema } from '../api/client';
import { ThemeProvider } from './theme-provider';
import { useTheme } from './theme-context';

const server = setupServer(
  http.get('/api/preferences', () => HttpResponse.json({ theme: 'system' })),
  http.put('/api/preferences', () => HttpResponse.json({ theme: 'dark' })),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());

function Control() {
  const { theme, setTheme } = useTheme();
  return (
    <select
      aria-label="Тема"
      value={theme}
      onChange={(event) => setTheme(themeSchema.parse(event.target.value))}
    >
      <option value="light">Светлая</option>
      <option value="dark">Тёмная</option>
      <option value="system">Системная</option>
    </select>
  );
}

it('applies a chosen dark theme and stores it for reopening', async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ThemeProvider>
        <Control />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Тема' }), 'dark');
  await waitFor(() => expect(document.documentElement).toHaveClass('dark'));
  expect(localStorage.getItem('saa-theme')).toBe('dark');
});

it('follows a system theme change while a manual choice keeps priority', async () => {
  const listeners = new Set<() => void>();
  const media = {
    matches: false,
    addEventListener: (_event: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_event: string, listener: () => void) => listeners.delete(listener),
  };
  vi.stubGlobal('matchMedia', () => media);
  localStorage.setItem('saa-theme', 'system');
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ThemeProvider>
        <Control />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(document.documentElement).not.toHaveClass('dark'));
  act(() => {
    media.matches = true;
    listeners.forEach((listener) => listener());
  });
  await waitFor(() => expect(document.documentElement).toHaveClass('dark'));
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Тема' }), 'light');
  act(() => {
    media.matches = false;
    listeners.forEach((listener) => listener());
  });
  expect(document.documentElement).not.toHaveClass('dark');
  vi.unstubAllGlobals();
});
