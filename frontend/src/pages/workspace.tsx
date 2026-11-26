import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import { Layers3, MessageSquare, Plus, SunMoon, ArrowRight } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router';
import { z } from 'zod';
import { Chat } from '../features/chat';
import {
  chatSchema,
  modelStatusSchema,
  request,
  scopeKey,
  themeSchema,
} from '../shared/api/client';
import { Button } from '../shared/ui/button';
import { useTheme } from '../shared/ui/theme-context';

export function Workspace() {
  const { chatId } = useParams();
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
        К диалогу
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
          <div>
            <span className="breadcrumb">
              Локальный проект <span>/</span> Чаты
            </span>
            <h2>{selected?.title ?? 'Рабочий чат'}</h2>
          </div>
          <ModelIndicator />
        </header>
        {chatId ? (
          <Chat key={chatId} chatId={chatId} />
        ) : (
          <div className="empty-workspace">
            <div className="welcome-icon">
              <Layers3 size={30} />
            </div>
            <span className="eyebrow">SOLUTION ARCHITECT AI</span>
            <h1>Место для продуманных решений</h1>
            <p>
              Обсуждайте требования и архитектуру в отдельных диалогах. Откройте сохранённый чат или
              начните новый.
            </p>
            <Button onClick={() => create.mutate()} disabled={create.isPending}>
              Начать обсуждение
              <ArrowRight size={17} />
            </Button>
          </div>
        )}
      </main>
    </div>
  );
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
