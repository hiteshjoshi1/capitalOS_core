import { useCallback, useEffect, useMemo, useState } from "react";
import { api, refreshAccessTokenNow, refreshSessionNow, setAccessToken, setAuthFailureHandler } from "../lib/api";
import type { AuthMe, AuthSession, UserPreferences } from "../lib/api";
import { useTheme } from "./ThemeContext";
import type { AccentColor, Theme } from "./ThemeContext";
import { DEFAULT_ACCENT, DEFAULT_THEME } from "./ThemeContext";
import { AuthContext } from "./authContextObject";
import type { AuthContextValue } from "./authContextObject";

const SESSION_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthMe | null>(null);
  const [loading, setLoading] = useState(true);
  const { applyServerPreferences } = useTheme();

  useEffect(() => {
    setAuthFailureHandler(() => {
      setAccessToken(null);
      setUser(null);
      setLoading(false);
    });
    return () => {
      setAuthFailureHandler(null);
    };
  }, []);

  // Apply the user's server-side theme/accent. Never blocks rendering: the ThemeProvider
  // already painted the localStorage values, so when the session response doesn't carry
  // preferences they're fetched in the background, and a failure keeps localStorage's.
  const syncPreferences = useCallback(
    (prefs: UserPreferences | null | undefined, isCancelled: () => boolean = () => false) => {
      const apply = (p: UserPreferences) => {
        if (isCancelled()) return;
        applyServerPreferences({ theme: p.theme as Theme, accent_color: p.accent_color as AccentColor });
      };
      if (prefs) {
        apply(prefs);
        return;
      }
      void api.getPreferences().then(apply, () => {
        // Non-fatal: localStorage values remain as fallback
      });
    },
    [applyServerPreferences],
  );

  // The user from a login/refresh response (#146); /auth/me only if it's missing.
  const userFromSession = useCallback(
    async (session: AuthSession): Promise<AuthMe> => session.user ?? (await api.authMe()),
    [],
  );

  useEffect(() => {
    // Cold load is ONE request (#146): /auth/refresh is unavoidable (the access token
    // lives only in memory, so after a reload the HttpOnly refresh cookie is the only
    // credential), and it now also returns the user and their preferences, which used
    // to be two more sequential calls (/auth/me, /auth/preferences) blocking every route.
    //
    // Route through the shared, deduped refresh (same helper realtime.ts uses) rather
    // than calling the endpoint directly. React 18 StrictMode double-invokes this effect
    // in dev — and overlapping mounts/timers/tabs can do the same in prod — so without
    // dedup, two concurrent /auth/refresh calls race on the same one-time-use refresh
    // token. It also already clears the access token and notifies authFailureHandler on
    // a definitive 401, so this effect just needs to react to the outcome.
    let cancelled = false;
    const isCancelled = () => cancelled;
    (async () => {
      const session = await refreshSessionNow();
      if (cancelled) return;
      if (!session) {
        // Definitive 401s already cleared user/token via authFailureHandler; transient
        // errors (network down, 5xx) leave the session as-is and just stop loading, so
        // the user sees the sign-in screen without being force-logged-out mid-session.
        setLoading(false);
        return;
      }
      try {
        const me = await userFromSession(session);
        if (cancelled) return;
        // Same tick as setUser, so the protected route's first paint has the theme.
        syncPreferences(session.preferences, isCancelled);
        setUser(me);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [syncPreferences, userFromSession]);

  useEffect(() => {
    if (!user) return;

    // Failure handling (clearing token/user on a definitive 401) is centralized in
    // refreshAccessTokenNow()'s authFailureHandler notification — nothing to do here,
    // and its in-flight dedup means an interval tick and a visibility change firing at
    // the same moment share one request instead of racing two.
    const refreshSession = () => {
      void refreshAccessTokenNow();
    };

    const intervalId = window.setInterval(refreshSession, SESSION_REFRESH_INTERVAL_MS);

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        refreshSession();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [user]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      login: async (username: string, password: string) => {
        const session = await api.authLogin({ username, password });
        setAccessToken(session.access_token);
        const me = await userFromSession(session);
        syncPreferences(session.preferences);
        setUser(me);
      },
      signup: async (username: string, password: string, displayName?: string) => {
        await api.authSignup({ username, password, display_name: displayName });
        const session = await api.authLogin({ username, password });
        setAccessToken(session.access_token);
        const me = await userFromSession(session);
        // A new user has no stored preferences: login returns the defaults.
        syncPreferences(session.preferences);
        setUser(me);
      },
      logout: async () => {
        try {
          await api.authLogout();
        } finally {
          setAccessToken(null);
          setUser(null);
          // Reset theme/accent to defaults so the next user starts from a clean
          // visual state. The access token is already null here, so isAuthenticated()
          // returns false and the effects will NOT send a PATCH to the server.
          applyServerPreferences({ theme: DEFAULT_THEME, accent_color: DEFAULT_ACCENT });
        }
      },
    }),
    [applyServerPreferences, loading, syncPreferences, user, userFromSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
