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

const THEME_STORAGE_KEY = "capitalos.theme";

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

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") {
    return;
  }

  document.documentElement.setAttribute("data-theme", theme);
}

type ThemeContextValue = {
  theme: Theme;
  setTheme: Dispatch<SetStateAction<Theme>>;
  persistTheme: (theme: Theme) => void;
  toggleTheme: () => void;
};

const fallbackSetTheme: Dispatch<SetStateAction<Theme>> = () => undefined;

const fallbackThemeContext: ThemeContextValue = {
  theme: "dark",
  setTheme: fallbackSetTheme,
  persistTheme: () => undefined,
  toggleTheme: () => undefined,
};

const ThemeContext = createContext<ThemeContextValue>(fallbackThemeContext);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const initial = readStoredTheme();
    applyTheme(initial);
    return initial;
  });

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

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      persistTheme,
      toggleTheme,
    }),
    [persistTheme, theme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
