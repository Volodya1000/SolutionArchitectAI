import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import boundaries from 'eslint-plugin-boundaries';
import importX from 'eslint-plugin-import-x';
import a11y from 'eslint-plugin-jsx-a11y';
import hooks from 'eslint-plugin-react-hooks';
import refresh from 'eslint-plugin-react-refresh';
import ts from 'typescript-eslint';

const allow = (from, to) => ({
  from: { element: { type: from } },
  allow: { to: { element: { type: to } } },
});

export default ts.config(
  { ignores: ['dist/**', 'node_modules/**', 'playwright-report/**', 'test-results/**'] },
  js.configs.recommended,
  {
    files: ['**/*.ts', '**/*.tsx'],
    extends: [ts.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: {
      'react-hooks': hooks,
      'jsx-a11y': a11y,
      'react-refresh': refresh,
      boundaries,
      'import-x': importX,
    },
    settings: {
      ...importX.flatConfigs.typescript.settings,
      'import-x/resolver': { typescript: { project: './tsconfig.json' } },
      'import/resolver': { typescript: { project: './tsconfig.json' } },
      'boundaries/root-path': import.meta.dirname,
      'boundaries/elements': [
        { type: 'app', pattern: 'src/app' },
        { type: 'pages', pattern: 'src/pages' },
        { type: 'features', pattern: 'src/features/*', capture: ['name'] },
        { type: 'shared', pattern: 'src/shared/*' },
        { type: 'test', pattern: 'src/test' },
      ],
      'boundaries/files': [{ pattern: 'src/main.tsx', category: 'entry' }],
    },
    rules: {
      ...hooks.configs.recommended.rules,
      ...a11y.configs.recommended.rules,
      'react-refresh/only-export-components': ['error', { allowConstantExport: true }],
      'import-x/no-cycle': 'error',
      complexity: ['error', { max: 10 }],
      'max-depth': ['error', { max: 3 }],
      'max-nested-callbacks': ['error', { max: 3 }],
      'boundaries/dependencies': [
        'error',
        {
          default: 'disallow',
          policies: [
            {
              from: { file: { categories: 'entry' } },
              allow: { to: { element: { type: 'app' } } },
            },
            allow('app', ['pages', 'features', 'shared']),
            allow('pages', ['features', 'shared']),
            allow('features', ['shared']),
            allow('shared', ['shared']),
            {
              from: { element: { type: 'features' } },
              allow: { to: { element: { type: 'features', fileInternalPath: 'index.ts' } } },
            },
          ],
        },
      ],
    },
  },
  prettier,
);
