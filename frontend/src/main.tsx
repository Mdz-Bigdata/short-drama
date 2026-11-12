import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { getLocale, loadLocale } from './i18n'
import { SharedCanvasEntry } from './features/share/SharedCanvasEntry'
import { sharedCanvasToken } from './features/share/sharedCanvasRoute'

// A read-only canvas link (/share/canvas/<token>) opens on its own page instead of the app.
const shareToken = sharedCanvasToken(window.location.pathname)

// A remembered English or Vietnamese interface loads its dictionary before the first render;
// Chinese, the default, renders at once. A failed load still renders, in Chinese.
loadLocale(getLocale()).catch(() => undefined).finally(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      {shareToken ? <SharedCanvasEntry token={shareToken} /> : <App />}
    </StrictMode>,
  )
})
