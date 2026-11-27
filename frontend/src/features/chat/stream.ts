import { type Run, type Snapshot } from '../../shared/api/client';

export function reconcileHistory(current: Snapshot | undefined, incoming: Snapshot): Snapshot {
  if (!current || current.chat.id !== incoming.chat.id) return incoming;
  const incomingRuns = new Map(incoming.runs.map((run) => [run.id, run]));
  for (const run of current.runs) {
    const older = incomingRuns.get(run.id);
    if (!older || run.sequence >= older.sequence) incomingRuns.set(run.id, run);
  }
  const runs = [...incomingRuns.values()];
  const byMessage = new Map(runs.map((run) => [run.assistant_message_id, run]));
  const messages = new Map(current.messages.map((message) => [message.id, message]));
  for (const message of incoming.messages) messages.set(message.id, message);
  return {
    ...incoming,
    runs,
    messages: [...messages.values()]
      .sort((left, right) => left.position - right.position)
      .map((message) => {
        const run = byMessage.get(message.id);
        return run ? { ...message, content: run.content, incomplete: run.incomplete } : message;
      }),
  };
}

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
