/** The path a canvas share link opens: `/share/canvas/<token>`, as the backend hands it out. */
const SHARED_CANVAS_PATH = /^\/share\/canvas\/([A-Za-z0-9_-]{16,64})$/;

/** The share token when this page is a read-only canvas link, else null (the app itself). */
export function sharedCanvasToken(pathname: string): string | null {
  return SHARED_CANVAS_PATH.exec(pathname)?.[1] ?? null;
}
