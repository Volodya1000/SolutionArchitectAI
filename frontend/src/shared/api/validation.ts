export const MESSAGE_LIMIT = 16000;
export const MESSAGE_LIMIT_HINT = 'Не более 16 000 символов в сообщении.';

export function messageLength(text: string): number {
  return Array.from(text.trim()).length;
}

export class InputValidationError extends Error {}
