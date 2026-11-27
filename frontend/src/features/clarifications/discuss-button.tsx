import { useNavigate } from 'react-router';
import {
  discussionCommandSchema,
  recoverDiscussion,
  startDiscussion,
  type DiscussionSubject,
} from '../../shared/api/discussions';
import { useInvalidateClarifications } from '../../shared/api/use-clarifications';
import { Button } from '../../shared/ui/button';
import { usePersistedCommand } from './use-persisted-command';

export function DiscussButton({ subject }: { subject: DiscussionSubject }) {
  return <DiscussionCommandButton key={JSON.stringify(subject)} subject={subject} />;
}

function DiscussionCommandButton({ subject }: { subject: DiscussionSubject }) {
  const navigate = useNavigate();
  const invalidate = useInvalidateClarifications();
  const state = usePersistedCommand({
    key: `discussion:${JSON.stringify(subject)}`,
    schema: discussionCommandSchema,
    recover: recoverDiscussion,
    execute: startDiscussion,
    onSuccess: async (chat) => {
      await invalidate();
      await navigate(`/chats/${encodeURIComponent(chat.id)}`);
    },
  });
  return (
    <div>
      <Button
        variant="outline"
        disabled={state.mutation.isPending || state.recovery.isFetching || state.recovery.isError}
        onClick={() => state.submit({ operation_id: crypto.randomUUID(), subject })}
      >
        {state.pending ? 'Повторить обсуждение' : 'Обсудить'}
      </Button>
      {state.mutation.isError && (
        <p className="notice error-text" role="alert">
          {state.mutation.error.message}
        </p>
      )}
      {state.recovery.isError && (
        <p role="alert">
          Не удалось проверить обсуждение.{' '}
          <Button
            onClick={() => {
              void state.recovery.refetch();
            }}
          >
            Проверить операцию
          </Button>
        </p>
      )}
    </div>
  );
}
