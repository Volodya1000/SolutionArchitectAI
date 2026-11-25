import { MessagePrimitive } from '@assistant-ui/react';
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown';
import { Bot, UserRound } from 'lucide-react';

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
    <MessagePrimitive.Root className="message assistant-message">
      <div className="avatar bot-avatar">
        <Bot size={18} />
      </div>
      <div className="message-body">
        <div className="message-author">SolutionArchitectAI</div>
        <div className="markdown">
          <MessagePrimitive.Content components={{ Text: MarkdownText }} />
        </div>
      </div>
    </MessagePrimitive.Root>
  );
}

function MarkdownText() {
  return <MarkdownTextPrimitive />;
}
