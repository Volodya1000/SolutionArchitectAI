import { type Run, type Snapshot } from '../../shared/api/client';

export function applyRunSnapshot(current: Run, incoming: Run, chatId: string): Run {
  if (
    incoming.chat_id !== chatId ||
    incoming.id !== current.id ||
    incoming.sequence <= current.sequence
  )
    return current;
  return incoming;
}

export function mergeSnapshot(
  current: Snapshot | undefined,
  incoming: Run,
  chatId: string,
): Snapshot | undefined {
  if (!current || incoming.chat_id !== chatId) return current;
  const previous = current.runs.find((run) => run.id === incoming.id);
  const run = previous ? applyRunSnapshot(previous, incoming, chatId) : incoming;
  if (run === previous) return current;
  return {
    ...current,
    messages: current.messages.map((message) =>
      message.id === run.assistant_message_id
        ? { ...message, content: run.content, incomplete: run.incomplete }
        : message,
    ),
    runs: [...current.runs.filter((item) => item.id !== run.id), run],
  };
}
