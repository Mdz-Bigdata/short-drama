import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { getLocale, loadLocale } from './i18n'

// A remembered English or Vietnamese interface loads its dictionary before the first render;
// Chinese, the default, renders at once. A failed load still renders, in Chinese.
loadLocale(getLocale()).catch(() => undefined).finally(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
