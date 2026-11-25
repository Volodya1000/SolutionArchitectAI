import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  ThreadPrimitive,
  useExternalStoreRuntime,
  useAui,
} from '@assistant-ui/react';
import { ArrowUp, Square, Sparkles } from 'lucide-react';
import { useEffect } from 'react';
import { terminal, type Message, type Run } from '../../shared/api/client';
import { Button } from '../../shared/ui/button';
import { AssistantMessage, UserMessage } from './messages';
import { useChat } from './use-chat';

type ChatState = ReturnType<typeof useChat>;
const statuses = {
  queued: 'В очереди',
  running: 'Формируется ответ…',
  cancelling: 'Останавливаем генерацию…',
  cancelled: 'Генерация отменена. Частичный ответ сохранён.',
  failed: 'Ответ не завершён. Можно отправить новый запрос.',
  completed: 'Ответ завершён',
};

export function Chat({ chatId }: { chatId: string }) {
  const state = useChat(chatId);
  const runtime = useExternalStoreRuntime<Message>({
    messages: state.query.data?.messages ?? [],
    isRunning: Boolean(state.run),
    convertMessage: (message) => ({
      id: message.id,
      role: message.role,
      content: [{ type: 'text', text: message.content }],
    }),
    onNew: async (message) => {
      const text = message.content
        .filter((part) => part.type === 'text')
        .map((part) => part.text)
        .join('\n');
      await state.send.mutateAsync(text);
      sessionStorage.removeItem(`draft:${chatId}`);
    },
    onCancel: () => state.cancel.mutateAsync(),
  });
  if (state.query.isPending)
    return (
      <div className="center-state" role="status">
        Загружаем историю…
      </div>
    );
  if (state.query.isError)
    return (
      <div className="center-state" role="alert">
        <p>История недоступна. Проверьте подключение.</p>
        <Button
          onClick={() => {
            void state.query.refetch();
          }}
        >
          Повторить
        </Button>
      </div>
    );
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <Conversation state={state} chatId={chatId} />
    </AssistantRuntimeProvider>
  );
}

function Welcome() {
  return (
    <div className="welcome">
      <div className="welcome-icon">
        <Sparkles size={26} />
      </div>
      <span className="eyebrow">ОТ ТРЕБОВАНИЙ К РЕШЕНИЯМ</span>
      <h1>Обсудим вашу архитектуру</h1>
      <p>
        Опишите задачу, исследуйте варианты и уточните границы системы. История этого диалога
        сохранится.
      </p>
      <div className="suggestions">
        <span>Границы компонентов</span>
        <span>Потоки данных</span>
        <span>Компромиссы решений</span>
      </div>
    </div>
  );
}

function RunStatus({ run }: { run: Run | undefined }) {
  if (!run) return null;
  return (
    <div className={`run-status ${run.status === 'failed' ? 'error-text' : ''}`} role="status">
      {statuses[run.status]}
      {!terminal(run) && <span className="activity-dot" />}
    </div>
  );
}

function SendErrors({ state }: { state: ChatState }) {
  const aui = useAui();
  if (!state.send.isError && !state.cancel.isError) return null;
  const retry = () => {
    if (!state.pending.current) return;
    state.send.mutate(state.pending.current.content, {
      onSuccess: () => {
        aui.composer.setText('');
        const chatId = state.query.data?.chat.id;
        if (chatId) sessionStorage.removeItem(`draft:${chatId}`);
      },
    });
  };
  return (
    <div className="notice error-text" role="alert">
      <p>{state.send.error?.message ?? state.cancel.error?.message}</p>
      {state.pending.current && (
        <Button variant="ghost" onClick={retry}>
          Повторить отправку
        </Button>
      )}
    </div>
  );
}

function Composer({ state, chatId }: { state: ChatState; chatId: string }) {
  const aui = useAui();
  useEffect(() => {
    aui.composer.setText(sessionStorage.getItem(`draft:${chatId}`) ?? '');
  }, [aui, chatId]);
  return (
    <div className="composer-area">
      {state.connectionError && (
        <p role="status" className="notice">
          Соединение прервано. Восстанавливаем сохранённый ответ…
        </p>
      )}
      <SendErrors state={state} />
      <ComposerPrimitive.Root className="composer">
        <ComposerPrimitive.Input
          aria-label="Сообщение"
          placeholder="Опишите задачу или задайте вопрос…"
          className="composer-input"
          onChange={(event) => sessionStorage.setItem(`draft:${chatId}`, event.target.value)}
        />
        <div className="composer-actions">
          <span>Enter — отправить · Shift + Enter — новая строка</span>
          {state.run ? (
            <ComposerPrimitive.Cancel asChild>
              <Button
                aria-label="Остановить генерацию"
                disabled={state.run.status === 'cancelling'}
              >
                <Square size={16} />
              </Button>
            </ComposerPrimitive.Cancel>
          ) : (
            <ComposerPrimitive.Send asChild>
              <Button aria-label="Отправить сообщение" disabled={state.send.isPending}>
                <ArrowUp size={19} />
              </Button>
            </ComposerPrimitive.Send>
          )}
        </div>
      </ComposerPrimitive.Root>
      <p className="composer-note">ИИ может ошибаться. Архитектурные решения принимает человек.</p>
    </div>
  );
}

function Conversation({ state, chatId }: { state: ChatState; chatId: string }) {
  const data = state.query.data;
  return (
    <ThreadPrimitive.Root className="thread">
      <ThreadPrimitive.Viewport className="thread-viewport">
        {data?.messages.length === 0 && <Welcome />}
        <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        <RunStatus run={data?.runs.at(-1)} />
      </ThreadPrimitive.Viewport>
      <Composer state={state} chatId={chatId} />
    </ThreadPrimitive.Root>
  );
}
