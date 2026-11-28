import { z } from 'zod';
import { zDiscussionSubject, zCreateDiscussion, zDiscussionView } from './generated/zod.gen';
import { chatSchema } from './client';
import { resourceRequest } from './resource-client';
import { ApiError } from './api-error';
import { clarificationSchema } from './clarifications';

export type DiscussionSubject = z.infer<typeof zDiscussionSubject>;
export const discussionCommandSchema = zCreateDiscussion;
export type DiscussionCommand = z.input<typeof discussionCommandSchema>;
export const discussionSchema = zDiscussionView;
export type DiscussionBinding = z.infer<typeof discussionSchema>;
export const readDiscussion = (id: string) =>
  resourceRequest(`/chats/${encodeURIComponent(id)}/discussion`, discussionSchema.nullable());
export const readDiscussionClarifications = (id: string) =>
  resourceRequest(
    `/chats/${encodeURIComponent(id)}/discussion/clarifications`,
    clarificationSchema.nullable(),
  );
export const startDiscussion = (command: DiscussionCommand) =>
  resourceRequest('/discussions', chatSchema, { method: 'POST', body: JSON.stringify(command) });
export async function recoverDiscussion(id: string) {
  try {
    return await resourceRequest(`/discussion-operations/${encodeURIComponent(id)}`, chatSchema);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
