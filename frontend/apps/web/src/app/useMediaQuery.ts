import { breakpoints } from '@tricklens/tokens';
import { useMemo, useSyncExternalStore } from 'react';

function subscribe(query: string) {
  return (onChange: () => void) => {
    if (typeof window.matchMedia !== 'function') return () => {};
    const mql = window.matchMedia(query);
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  };
}

/** Whether a media query matches, kept in sync as the window changes. False where matchMedia is missing (tests). */
export function useMediaQuery(query: string): boolean {
  const sub = useMemo(() => subscribe(query), [query]);
  return useSyncExternalStore(
    sub,
    () => typeof window.matchMedia === 'function' && window.matchMedia(query).matches,
    () => false,
  );
}

/** The desktop layout's breakpoint, the same one AppShell's CSS uses. */
export const useIsDesktop = () => useMediaQuery(`(min-width: ${breakpoints.desktop}px)`);
