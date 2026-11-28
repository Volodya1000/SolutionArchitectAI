export function fixtureId(label: string): string {
  let hash = 2166136261;
  for (const character of label) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619) >>> 0;
  const hexadecimal = hash.toString(16).padStart(8, '0');
  return `${hexadecimal}-0000-4000-8000-${hexadecimal}0000`;
}

export function fixtureHash(label: string): string {
  const hexadecimal = fixtureId(label).replaceAll('-', '');
  return hexadecimal + hexadecimal;
}

export const storedModelProfileFixture = {
  approximate_chars_per_token: 1,
  base_url: 'http://fake-llm:8000/v1',
  concurrency: 1,
  context_window: 16000,
  model: 'fake-chat',
  output_limit: 2048,
  retry: {
    network_retries: 1,
    validation_retries: 1,
    max_total_requests: 128,
    deadline_seconds: 120,
    request_timeout_seconds: 30,
    backoff_initial: 0,
    backoff_max: 0,
    jitter: 0,
  },
  service_tokens: 256,
  structured_mode: 'native_json_schema' as const,
  temperature: 0.2,
};

export const clarificationModelProfileFixture = {
  name: 'fake-chat',
  mode: 'native_json_schema' as const,
  context_window: 16000,
  output_limit: 2048,
  service_tokens: 256,
};
