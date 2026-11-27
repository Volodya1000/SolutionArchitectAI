import { z } from 'zod';
import { chatSchema } from './client';
import { resourceRequest } from './resource-client';
import { ApiError } from './api-error';
import { clarificationSchema } from './clarifications';

const subjectSchema = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('requirement'), run_id: z.string(), requirement_id: z.string() }),
  z.object({
    kind: z.literal('source'),
    version_id: z.string(),
    fragment_id: z.string(),
    analysis_id: z.string().nullable(),
  }),
]);
export type DiscussionSubject = z.infer<typeof subjectSchema>;
export const discussionCommandSchema = z.object({
  operation_id: z.string(),
  subject: subjectSchema,
});
export type DiscussionCommand = z.infer<typeof discussionCommandSchema>;
export const discussionSchema = z.object({
  chat_id: z.string(),
  kind: z.enum(['requirement', 'source']),
  title: z.string(),
  analysis_id: z.string().nullable(),
  requirement_id: z.string().nullable(),
  version_id: z.string().nullable(),
  fragment_id: z.string().nullable(),
  version_ids: z.array(z.string()),
  history_id: z.string().nullable(),
  backlink: z.string(),
});
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
