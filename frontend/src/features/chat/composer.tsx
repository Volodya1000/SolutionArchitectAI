import { ComposerPrimitive, useAui, useAuiState } from '@assistant-ui/react';
import { ArrowUp, Square } from 'lucide-react';
import { useEffect } from 'react';
import { MESSAGE_LIMIT, MESSAGE_LIMIT_HINT, messageLength } from '../../shared/api/validation';
import { sessionStore } from '../../shared/ui/session-storage';
import { Button } from '../../shared/ui/button';
import type { useChat } from './use-chat';

type ChatState = ReturnType<typeof useChat>;

function SendErrors({ state }: { state: ChatState }) {
  const aui = useAui();
  const chatId = state.query.data?.chat.id;
  useEffect(() => {
    if (!state.send.isError || !chatId || aui.composer.getState().text) return;
    const draft = sessionStore.get(`draft:${chatId}`);
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

export function Composer({ state, chatId }: { state: ChatState; chatId: string }) {
  const aui = useAui();
  const text = useAuiState((s) => s.composer.text);
  const tooLong = messageLength(text) > MESSAGE_LIMIT;
  useEffect(() => {
    aui.composer.setText(sessionStore.get(`draft:${chatId}`) ?? '');
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
          onChange={(event) => sessionStore.set(`draft:${chatId}`, event.target.value)}
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
            <ComposerPrimitive.Send asChild disabled={state.send.isPending || tooLong}>
              <Button className="composer-send" aria-label="Отправить сообщение">
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
