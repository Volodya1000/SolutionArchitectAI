import { useEffect } from 'react';
import { type QueryClient, useQueryClient } from '@tanstack/react-query';
import { scopeKey } from './client';

const channelName = `solutionarchitectai:clarifications:${scopeKey.join(':')}`;
const sender = crypto.randomUUID();
const subscriptions = new WeakMap<QueryClient, { channel: BroadcastChannel; users: number }>();

export function useClarificationSync() {
  const client = useQueryClient();
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return;
    let subscription = subscriptions.get(client);
    if (!subscription) {
      const channel = new BroadcastChannel(channelName);
      channel.onmessage = (event: MessageEvent<unknown>) => {
        const message = event.data;
        if (
          typeof message === 'object' &&
          message !== null &&
          'sender' in message &&
          message.sender !== sender
        )
          void client.invalidateQueries({ queryKey: scopeKey });
      };
      subscription = { channel, users: 0 };
      subscriptions.set(client, subscription);
    }
    subscription.users++;
    return () => {
      subscription.users--;
      if (subscription.users === 0) {
        subscription.channel.close();
        subscriptions.delete(client);
      }
    };
  }, [client]);
}

export function announceClarificationChange() {
  if (typeof BroadcastChannel === 'undefined') return;
  const channel = new BroadcastChannel(channelName);
  channel.postMessage({ sender });
  channel.close();
}
