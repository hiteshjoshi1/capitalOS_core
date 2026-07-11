/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { useEffect } from "react";
import { api } from "../lib/api";

export type Theme = "dark" | "light";
export type AccentColor = "#0f7a5c" | "#2b6ddb" | "#8650d9" | "#b5842a";

export const ACCENT_SWATCHES: AccentColor[] = ["#0f7a5c", "#2b6ddb", "#8650d9", "#b5842a"];
const DEFAULT_ACCENT: AccentColor = "#0f7a5c";

const THEME_STORAGE_KEY = "capitalos.theme";
const ACCENT_STORAGE_KEY = "capitalos.accent";

function readStoredTheme(): Theme {
  if (typeof window === "undefined") {
    return "dark";
  }

  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "dark" || stored === "light") {
    return stored;
  }

  return "dark";
}

function readStoredAccent(): AccentColor {
  if (typeof window === "undefined") {
    return DEFAULT_ACCENT;
  }

  const stored = window.localStorage.getItem(ACCENT_STORAGE_KEY);
  if (stored && (ACCENT_SWATCHES as string[]).includes(stored)) {
    return stored as AccentColor;
  }

  return DEFAULT_ACCENT;
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") {
    return;
  }

  document.documentElement.setAttribute("data-theme", theme);
}

function applyAccent(accent: AccentColor, theme: Theme) {
  if (typeof document === "undefined") {
    return;
  }

  const softPercent = theme === "dark" ? "20%" : "10%";
  const root = document.documentElement.style;
  root.setProperty("--accent", accent);
  root.setProperty("--accent-soft", `color-mix(in srgb, ${accent} ${softPercent}, transparent)`);
  root.setProperty("--accentSoft", `color-mix(in srgb, ${accent} ${softPercent}, transparent)`);
}

type ThemeContextValue = {
  theme: Theme;
  setTheme: Dispatch<SetStateAction<Theme>>;
  persistTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  accent: AccentColor;
  setAccent: Dispatch<SetStateAction<AccentColor>>;
  /** Apply server-loaded preferences without triggering a PATCH back to the server. */
  applyServerPreferences: (prefs: { theme: Theme; accent_color: AccentColor }) => void;
};

const fallbackSetTheme: Dispatch<SetStateAction<Theme>> = () => undefined;
const fallbackSetAccent: Dispatch<SetStateAction<AccentColor>> = () => undefined;

const fallbackThemeContext: ThemeContextValue = {
  theme: "dark",
  setTheme: fallbackSetTheme,
  persistTheme: () => undefined,
  toggleTheme: () => undefined,
  accent: DEFAULT_ACCENT,
  setAccent: fallbackSetAccent,
  applyServerPreferences: () => undefined,
};

const ThemeContext = createContext<ThemeContextValue>(fallbackThemeContext);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const initial = readStoredTheme();
    applyTheme(initial);
    return initial;
  });
  const [accent, setAccent] = useState<AccentColor>(() => readStoredAccent());

  // Tracks how many state changes originated from the server — those should not be
  // PATCHed back (they're already persisted server-side). Decremented in each effect
  // that runs as a result of applyServerPreferences(); a fallback setTimeout resets
  // the counter to 0 for cases where the value didn't actually change (React bails out).
  const serverSyncDepth = useRef(0);
  const serverSyncTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const applyServerPreferences = useCallback((prefs: { theme: Theme; accent_color: AccentColor }) => {
    if (serverSyncTimer.current !== null) {
      clearTimeout(serverSyncTimer.current);
    }
    serverSyncDepth.current += 2; // one decrement per effect (theme + accent)
    setTheme(prefs.theme);
    setAccent(prefs.accent_color);
    // Safety reset: if values were unchanged React won't fire the effects, so ensure
    // the counter is cleared after the current microtask queue drains.
    serverSyncTimer.current = setTimeout(() => {
      serverSyncDepth.current = 0;
      serverSyncTimer.current = null;
    }, 0);
  }, []);

  const persistTheme = useCallback((nextTheme: Theme) => {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }, []);

  useEffect(() => {
    applyTheme(theme);
    persistTheme(theme);
    if (serverSyncDepth.current > 0) {
      serverSyncDepth.current = Math.max(0, serverSyncDepth.current - 1);
      return;
    }
    if (api.isAuthenticated?.()) {
      void api.patchPreferences?.({ theme }).catch(() => {});
    }
  }, [persistTheme, theme]);

  // Visual-only: re-apply accent CSS whenever accent or theme changes (theme affects
  // the soft-blend percentage). Does NOT send a PATCH — theme changes must not trigger
  // a redundant accent PATCH that races against the theme PATCH.
  useEffect(() => {
    applyAccent(accent, theme);
  }, [accent, theme]);

  // Persistence: localStorage write + server PATCH only when accent itself changes.
  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(ACCENT_STORAGE_KEY, accent);
    }
    if (serverSyncDepth.current > 0) {
      serverSyncDepth.current = Math.max(0, serverSyncDepth.current - 1);
      return;
    }
    if (api.isAuthenticated?.()) {
      void api.patchPreferences?.({ accent_color: accent }).catch(() => {});
    }
  }, [accent]);

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      persistTheme,
      toggleTheme,
      accent,
      setAccent,
      applyServerPreferences,
    }),
    [accent, applyServerPreferences, persistTheme, theme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
