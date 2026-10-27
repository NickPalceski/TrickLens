import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from 'react';

/** "system" follows the OS setting; the other two override it. */
export type ThemePreference = 'light' | 'dark' | 'system';

export const THEME_STORAGE_KEY = 'tricklens:theme';

function readStored(): ThemePreference {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

/** Sets data-theme on <html>; the token CSS keys both themes off it. */
export function applyTheme(pref: ThemePreference) {
  const root = document.documentElement;
  if (pref === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', pref);
}

interface ThemeContextValue {
  preference: ThemePreference;
  setPreference: (pref: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setState] = useState<ThemePreference>(() => {
    const pref = readStored();
    applyTheme(pref);
    return pref;
  });

  const setPreference = useCallback((pref: ThemePreference) => {
    setState(pref);
    applyTheme(pref);
    try {
      if (pref === 'system') localStorage.removeItem(THEME_STORAGE_KEY);
      else localStorage.setItem(THEME_STORAGE_KEY, pref);
    } catch {
      // Storage can be unavailable (private windows); the choice still
      // applies for this visit.
    }
  }, []);

  const value = useMemo(() => ({ preference, setPreference }), [preference, setPreference]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme() needs a <ThemeProvider> above it');
  return ctx;
}
