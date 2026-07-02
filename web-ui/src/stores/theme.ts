import { create } from 'zustand';

/**
 * Celesnity theme scopes — "Two skies, one identity."
 *  - cosmos:   dark, the brand default (cosmic-black surfaces, nebula glow)
 *  - daybreak: light (cloud-white / lavender-mist surfaces, soft cool shadow)
 *
 * The scope is applied as a class on <html> (`.cosmos` / `.daybreak`) plus a
 * `data-surface` hint so dark-surface helpers (focus ring, selection) resolve.
 */
export type Theme = 'cosmos' | 'daybreak';

const STORAGE_KEY = 'atria-theme';

function readInitial(): Theme {
  if (typeof window === 'undefined') return 'cosmos';
  const saved = window.localStorage.getItem(STORAGE_KEY);
  return saved === 'daybreak' ? 'daybreak' : 'cosmos';
}

/** Apply the scope class + surface hint to <html>. Safe to call pre-React. */
export function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.remove('cosmos', 'daybreak');
  root.classList.add(theme);
  root.setAttribute('data-surface', theme === 'cosmos' ? 'dark' : 'light');
  root.style.colorScheme = theme === 'cosmos' ? 'dark' : 'light';
}

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: readInitial(),
  setTheme: (theme) => {
    applyTheme(theme);
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* ignore quota / privacy-mode failures */
    }
    set({ theme });
  },
  toggleTheme: () => {
    const next: Theme = get().theme === 'cosmos' ? 'daybreak' : 'cosmos';
    get().setTheme(next);
  },
}));
