import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  ThreadPrimitive,
  useExternalStoreRuntime,
  useAui,
  useAuiState,
} from '@assistant-ui/react';
import { ArrowUp, Square, Sparkles } from 'lucide-react';
import { useEffect } from 'react';
import { type Message } from '../../shared/api/client';
import { MESSAGE_LIMIT, MESSAGE_LIMIT_HINT, messageLength } from '../../shared/api/validation';
import { Button } from '../../shared/ui/button';
import { AssistantMessage, UserMessage } from './messages';
import { useChat } from './use-chat';

type ChatState = ReturnType<typeof useChat>;

export function Chat({ chatId }: { chatId: string }) {
  const state = useChat(chatId);
  const runtime = useExternalStoreRuntime<Message>({
    messages: state.query.data?.messages ?? [],
    isRunning: Boolean(state.run),
    convertMessage: (message) => ({
      id: message.id,
      role: message.role,
      content: [{ type: 'text', text: message.content }],
      metadata: {
        custom: {
          incomplete: message.incomplete,
          run: state.query.data?.runs.find((run) => run.assistant_message_id === message.id),
        },
      },
    }),
    onNew: async (message) => {
      const text = message.content
        .filter((part) => part.type === 'text')
        .map((part) => part.text)
        .join('\n');
      await state.send.mutateAsync(text);
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

function SendErrors({ state }: { state: ChatState }) {
  const aui = useAui();
  const chatId = state.query.data?.chat.id;
  useEffect(() => {
    if (!state.send.isError || !chatId || aui.composer.getState().text) return;
    const draft = sessionStorage.getItem(`draft:${chatId}`);
    if (draft) aui.composer.setText(draft);
  }, [aui, chatId, state.send.isError]);
  if (!state.send.isError && !state.cancel.isError) return null;
  const retry = () => {
    if (!state.pending.current) return;
    const content = state.pending.current.content;
    state.send.mutate(content, {
      onSuccess: () => {
        if (aui.composer.getState().text === content) aui.composer.setText('');
      },
    });
  };
  return (
    <div className="notice error-text" role="alert">
      <p>{state.send.error?.message ?? state.cancel.error?.message}</p>
      {state.pending.current && (
        <Button variant="ghost" onClick={retry} disabled={state.send.isPending}>
          Повторить отправку
        </Button>
      )}
    </div>
  );
}

function Composer({ state, chatId }: { state: ChatState; chatId: string }) {
  const aui = useAui();
  const text = useAuiState((s) => s.composer.text);
  const tooLong = messageLength(text) > MESSAGE_LIMIT;
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
      <p id="message-limit" className="composer-note" role={tooLong ? 'alert' : undefined}>
        {MESSAGE_LIMIT_HINT}
      </p>
      <ComposerPrimitive.Root className="composer">
        <ComposerPrimitive.Input
          aria-label="Сообщение"
          aria-describedby="message-limit"
          aria-invalid={tooLong}
          placeholder="Опишите задачу или задайте вопрос…"
          className="composer-input"
          onChange={(event) => sessionStorage.setItem(`draft:${chatId}`, event.target.value)}
          onKeyDown={(event) => {
            if ((tooLong || state.send.isPending) && event.key === 'Enter' && !event.shiftKey)
              event.preventDefault();
          }}
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
              <Button aria-label="Отправить сообщение" disabled={state.send.isPending || tooLong}>
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
      </ThreadPrimitive.Viewport>
      <Composer state={state} chatId={chatId} />
    </ThreadPrimitive.Root>
  );
}
