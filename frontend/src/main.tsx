import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { getLocale, loadLocale } from './i18n'
import { bootstrapAppearance } from './appearance/appearance'
import { SharedCanvasEntry } from './features/share/SharedCanvasEntry'
import { sharedCanvasToken } from './features/share/sharedCanvasRoute'

// A read-only canvas link (/share/canvas/<token>) opens on its own page instead of the app.
const shareToken = sharedCanvasToken(window.location.pathname)

// A remembered English or Vietnamese interface loads its dictionary before the first render;
// Chinese, the default, renders at once. A failed load still renders, in Chinese.
// The deployment's brand is read first too, so a custom brand never flashes the built-in name;
// no answer in time means the built-in appearance.
Promise.all([loadLocale(getLocale()).catch(() => undefined), bootstrapAppearance()]).finally(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      {shareToken ? <SharedCanvasEntry token={shareToken} /> : <App />}
    </StrictMode>,
  )
})
