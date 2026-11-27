import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import { preferencesSchema, themeSchema, type Theme } from '../api/client';
import { ThemeProvider } from './theme-provider';
import { useTheme } from './theme-context';

const server = setupServer(
  http.get('/api/preferences', () => HttpResponse.json({ theme: 'system' })),
  http.put('/api/preferences', () => HttpResponse.json({ theme: 'dark' })),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function Control() {
  const { theme, setTheme, savingFailed } = useTheme();
  return (
    <>
      <select
        aria-label="Тема"
        value={theme}
        onChange={(event) => setTheme(themeSchema.parse(event.target.value))}
      >
        <option value="light">Светлая</option>
        <option value="dark">Тёмная</option>
        <option value="system">Системная</option>
      </select>
      <output aria-label="Theme saving">{savingFailed ? 'Failed' : 'OK'}</output>
    </>
  );
}

it.each([200, 503])(
  'persists rapid theme choices in order when the earlier write returns %i',
  async (firstStatus) => {
    let releaseFirst = () => {};
    const firstWrite = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });
    let storedTheme: Theme = 'system';
    const receivedThemes: Theme[] = [];
    let writing = false;
    let concurrentWrite = false;
    server.use(
      http.put('/api/preferences', async ({ request }) => {
        const { theme } = preferencesSchema.parse(await request.json());
        receivedThemes.push(theme);
        concurrentWrite ||= writing;
        writing = true;
        if (theme === 'dark') {
          await firstWrite;
          if (firstStatus !== 200) {
            writing = false;
            return new HttpResponse(null, { status: firstStatus });
          }
        }
        storedTheme = theme;
        writing = false;
        return HttpResponse.json({ theme });
      }),
    );
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <ThemeProvider>
          <Control />
        </ThemeProvider>
      </QueryClientProvider>,
    );
    const control = screen.getByRole('combobox', { name: 'Тема' });
    await userEvent.selectOptions(control, 'dark');
    await waitFor(() => expect(receivedThemes).toEqual(['dark']));
    await userEvent.selectOptions(control, 'light');

    expect(control).toHaveValue('light');
    expect(document.documentElement).not.toHaveClass('dark');
    const writesBeforeRelease = [...receivedThemes];
    releaseFirst();

    await waitFor(() => expect(client.isMutating()).toBe(0));
    expect(writesBeforeRelease).toEqual(['dark']);
    expect(concurrentWrite).toBe(false);
    expect(receivedThemes).toEqual(['dark', 'light']);
    expect(storedTheme).toBe('light');
    expect(screen.getByLabelText('Theme saving')).toHaveTextContent('OK');
    expect(localStorage.getItem('saa-theme')).toBe('light');
  },
);

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
