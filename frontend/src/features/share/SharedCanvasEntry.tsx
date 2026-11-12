import { lazy, Suspense } from 'react';

// Loaded only when a share link is opened, so the app's own first load carries none of it.
const SharedCanvasPage = lazy(() => import('./SharedCanvasPage'));

/** What a read-only canvas link renders instead of the app: no login, no app shell. */
export function SharedCanvasEntry({ token }: { token: string }) {
  return (
    <Suspense fallback={null}>
      <SharedCanvasPage token={token} />
    </Suspense>
  );
}
