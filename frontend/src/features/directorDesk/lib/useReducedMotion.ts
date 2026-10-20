import { useEffect, useState } from 'react';

/**
 * Whether the person asked the system for less movement.
 *
 * The desk answers it in three places: the stylesheet drops its transitions, the director view
 * stops coasting after a drag, and a clip in the library waits to be asked instead of playing
 * itself under the pointer. Playback of a shot is always something the person started, so it
 * stays exactly as it is — previs is watched for its timing.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    try {
      return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch {
      return false;
    }
  });

  useEffect(() => {
    let media: MediaQueryList;
    try {
      media = window.matchMedia('(prefers-reduced-motion: reduce)');
    } catch {
      return undefined;
    }
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  return reduced;
}
