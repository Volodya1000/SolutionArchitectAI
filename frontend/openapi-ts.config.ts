import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: process.env['OPENAPI_INPUT'] ?? 'openapi.json',
  output: process.env['OPENAPI_OUTPUT'] ?? 'src/shared/api/generated',
  plugins: [
    '@hey-api/typescript',
    {
      name: 'zod',
      definitions: true,
      requests: true,
      responses: true,
      dates: { offset: true },
    },
  ],
});
