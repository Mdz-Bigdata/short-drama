import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

const LOCAL_ADDRESS = String.raw`/^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])/`

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    // The backend address comes from VITE_API_BASE_URL through api/client.ts.
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/api/client.ts', 'src/**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': ['error', {
        selector: `:matches(Literal[value=${LOCAL_ADDRESS}], TemplateElement[value.raw=${LOCAL_ADDRESS}])`,
        message: 'Do not hardcode a server address; build the URL from API_BASE in src/api/client.ts.',
      }],
    },
  },
])
