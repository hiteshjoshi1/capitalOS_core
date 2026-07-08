/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { useEffect } from "react";

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
};

const ThemeContext = createContext<ThemeContextValue>(fallbackThemeContext);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const initial = readStoredTheme();
    applyTheme(initial);
    return initial;
  });
  const [accent, setAccent] = useState<AccentColor>(() => readStoredAccent());

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
  }, [persistTheme, theme]);

  useEffect(() => {
    applyAccent(accent, theme);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(ACCENT_STORAGE_KEY, accent);
    }
  }, [accent, theme]);

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      persistTheme,
      toggleTheme,
      accent,
      setAccent,
    }),
    [accent, persistTheme, theme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
