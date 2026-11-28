import { spawnSync } from 'node:child_process';
import { fileURLToPath, URL } from 'node:url';
import process from 'node:process';

const root = fileURLToPath(new URL('../..', import.meta.url));
const result = spawnSync(
  'uv',
  [
    'run',
    '--locked',
    '--project',
    'backend',
    'python',
    '-m',
    'tools.api_contracts',
    ...process.argv.slice(2),
  ],
  { cwd: root, stdio: 'inherit', windowsHide: true },
);
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
