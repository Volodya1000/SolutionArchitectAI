import {
  AssistantRuntimeProvider,
  ThreadPrimitive,
  useExternalStoreRuntime,
} from '@assistant-ui/react';
import { Sparkles } from 'lucide-react';
import { useMemo } from 'react';
import { type Message } from '../../shared/api/client';
import { Button } from '../../shared/ui/button';
import { AssistantMessage, UserMessage } from './messages';
import { Composer } from './composer';
import { useChat } from './use-chat';

type ChatState = ReturnType<typeof useChat>;

export function Chat({ chatId }: { chatId: string }) {
  const state = useChat(chatId);
  const runsByMessage = useMemo(
    () => new Map(state.query.data?.runs.map((run) => [run.assistant_message_id, run])),
    [state.query.data?.runs],
  );
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
          run: runsByMessage.get(message.id),
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
  if (state.query.isError && !state.query.data)
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

function Conversation({ state, chatId }: { state: ChatState; chatId: string }) {
  const data = state.query.data;
  return (
    <ThreadPrimitive.Root className="thread">
      {state.query.isError && (
        <div className="notice error-text" role="alert">
          Не удалось обновить историю. Показана последняя загруженная переписка.
          <Button
            variant="ghost"
            onClick={() => {
              void state.query.refetch();
            }}
          >
            Повторить
          </Button>
        </div>
      )}
      <ThreadPrimitive.Viewport className="thread-viewport">
        {data?.messages.length === 0 && <Welcome />}
        <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
      </ThreadPrimitive.Viewport>
      <Composer state={state} chatId={chatId} />
    </ThreadPrimitive.Root>
  );
}
