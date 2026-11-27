import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Route, Routes } from 'react-router';
import { Workspace } from '../pages/workspace';
import { ThemeProvider } from '../shared/ui/theme-provider';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 1000 }, mutations: { retry: false } },
});
export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Workspace />} />
            <Route path="/chats/:chatId" element={<Workspace />} />
            <Route path="/documents" element={<Workspace />} />
            <Route path="/requirements" element={<Workspace />} />
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
