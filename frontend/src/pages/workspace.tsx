import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import { Layers3, MessageSquare, Plus, SunMoon, Files, ListChecks } from 'lucide-react';
import { Link, useLocation, useNavigate, useParams } from 'react-router';
import { z } from 'zod';
import {
  chatSchema,
  modelStatusSchema,
  request,
  scopeKey,
  themeSchema,
} from '../shared/api/client';
import { Button } from '../shared/ui/button';
import { useTheme } from '../shared/ui/theme-context';
import { WorkspaceContent, WorkspaceHeading, type WorkspaceSection } from './workspace-content';

export function Workspace() {
  const { chatId } = useParams();
  const location = useLocation();
  const section = workspaceSection(location.pathname);
  const navigate = useNavigate();
  const client = useQueryClient();
  const theme = useTheme();
  const chats = useQuery({
    queryKey: [...scopeKey, 'chats'],
    queryFn: () => request('/chats', z.array(chatSchema)),
  });
  const create = useMutation({
    mutationFn: () =>
      request('/chats', chatSchema, {
        method: 'POST',
        body: JSON.stringify({ title: `Диалог ${(chats.data?.length ?? 0) + 1}` }),
      }),
    onSuccess: async (chat) => {
      await client.invalidateQueries({ queryKey: [...scopeKey, 'chats'] });
      await navigate(`/chats/${chat.id}`);
    },
  });
  const selected = chats.data?.find((chat) => chat.id === chatId);
  return (
    <div className="workspace">
      <a className="skip-link" href="#conversation">
        К основному содержимому
      </a>
      <aside className="sidebar">
        <Link className="brand" to="/">
          <div className="brand-icon">
            <Layers3 size={21} />
          </div>
          <div>
            SolutionArchitect<span>AI WORKSPACE</span>
          </div>
        </Link>
        <div className="scope-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
        <div className="project-name">
          <span className="project-avatar">SA</span>
          <div>
            Локальный проект<small>Обсуждение архитектуры</small>
          </div>
        </div>
        <nav aria-label="Рабочее пространство" className="workspace-navigation">
          <Link
            className="chat-link"
            to="/documents"
            aria-current={section === 'documents' ? 'page' : undefined}
          >
            <Files size={16} />
            Документы
          </Link>
          <Link
            className="chat-link"
            to="/requirements"
            aria-current={section === 'requirements' ? 'page' : undefined}
          >
            <ListChecks size={16} />
            Требования
          </Link>
        </nav>
        <Button className="new-chat" onClick={() => create.mutate()} disabled={create.isPending}>
          <Plus size={17} />
          Новый чат
        </Button>
        <div className="section-label">
          ДИАЛОГИ <span>{chats.data?.length ?? 0}</span>
        </div>
        <ChatNavigation chats={chats} chatId={chatId} />
        {create.isError && (
          <p role="alert" className="notice error-text">
            {create.error.message}
          </p>
        )}
        <div className="sidebar-footer">
          <SunMoon size={17} />
          <label htmlFor="theme">Тема</label>
          <select
            id="theme"
            value={theme.theme}
            onChange={(event) => theme.setTheme(themeSchema.parse(event.target.value))}
          >
            <option value="light">Светлая</option>
            <option value="dark">Тёмная</option>
            <option value="system">Системная</option>
          </select>
        </div>
        {theme.savingFailed && (
          <p className="notice" role="status">
            Выбор сохранён на устройстве. Серверная настройка недоступна.
          </p>
        )}
      </aside>
      <main id="conversation">
        <header className="topbar">
          <WorkspaceHeading section={section} title={selected?.title} />
          <ModelIndicator />
        </header>
        <WorkspaceContent
          section={section}
          chatId={chatId}
          pending={create.isPending}
          create={() => create.mutate()}
        />
      </main>
    </div>
  );
}

function workspaceSection(path: string): WorkspaceSection {
  if (path === '/documents') return 'documents';
  if (path === '/requirements') return 'requirements';
  return 'chat';
}

function ModelIndicator() {
  const status = useQuery({
    queryKey: [...scopeKey, 'model'],
    queryFn: () => request('/model', modelStatusSchema),
    retry: false,
    refetchInterval: 30000,
  });
  const label = status.isPending
    ? 'Проверяем API модели…'
    : status.data?.available
      ? status.data.model
      : 'Модель недоступна';
  return (
    <span className="local-badge" role="status">
      <span />
      {label}
    </span>
  );
}

function ChatNavigation({
  chats,
  chatId,
}: {
  chats: UseQueryResult<z.infer<typeof chatSchema>[], Error>;
  chatId: string | undefined;
}) {
  return (
    <nav aria-label="Чаты" className="chat-list">
      {chats.data?.map((chat) => (
        <Link
          key={chat.id}
          to={`/chats/${chat.id}`}
          aria-current={chat.id === chatId ? 'page' : undefined}
          className="chat-link"
        >
          <MessageSquare size={16} />
          <span>{chat.title}</span>
        </Link>
      ))}
      {chats.isPending && <p role="status">Загружаем чаты…</p>}
      {chats.isError && (
        <p role="alert">
          Не удалось загрузить чаты.
          <Button
            variant="ghost"
            onClick={() => {
              void chats.refetch();
            }}
          >
            Повторить
          </Button>
        </p>
      )}
    </nav>
  );
}
