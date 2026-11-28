import { MessagePrimitive, useAuiState } from '@assistant-ui/react';
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown';
import { Bot, UserRound } from 'lucide-react';
import { runSchema, terminal } from '../../shared/api/client';

const statuses = {
  queued: 'В очереди',
  running: 'Формируется ответ…',
  waiting_input: 'Ожидает ответа архитектора',
  cancelling: 'Останавливаем генерацию…',
  cancelled: 'Генерация отменена. Частичный ответ сохранён.',
  failed: 'Ответ не завершён. Можно отправить новый запрос.',
  completed: 'Ответ завершён',
} as const;

export function UserMessage() {
  return (
    <MessagePrimitive.Root className="message user-message">
      <div className="avatar">
        <UserRound size={17} />
      </div>
      <div className="message-body">
        <div className="message-author">Вы</div>
        <MessagePrimitive.Content />
      </div>
    </MessagePrimitive.Root>
  );
}
export function AssistantMessage() {
  return (
    <MessagePrimitive.Root
      className="message assistant-message"
      role="article"
      aria-label="Ответ ассистента"
    >
      <div className="avatar bot-avatar">
        <Bot size={18} />
      </div>
      <div className="message-body">
        <div className="message-author">SolutionArchitectAI</div>
        <div className="markdown">
          <MessagePrimitive.Content components={{ Text: MarkdownText }} />
        </div>
        <MessageStatus />
      </div>
    </MessagePrimitive.Root>
  );
}

function MessageStatus() {
  const metadata = useAuiState((s) => s.message.metadata.custom);
  const parsed = runSchema.safeParse(metadata['run']);
  if (!parsed.success)
    return metadata['incomplete'] ? <p role="status">Ответ не завершён.</p> : null;
  const run = parsed.data;
  return (
    <div className={`run-status ${run.status === 'failed' ? 'error-text' : ''}`} role="status">
      {statuses[run.status]}
      {!terminal(run) && <span className="activity-dot" />}
    </div>
  );
}

function MarkdownText() {
  return <MarkdownTextPrimitive />;
}
