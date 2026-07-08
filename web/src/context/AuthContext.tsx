import { createContext, useEffect, useMemo, useState } from "react";
import { api, refreshAccessTokenNow, setAccessToken, setAuthFailureHandler } from "../lib/api";
import type { AuthMe } from "../lib/api";

type AuthContextValue = {
  user: AuthMe | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  signup: (username: string, password: string, displayName?: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: false,
  login: async () => {},
  signup: async () => {},
  logout: async () => {},
});

const SESSION_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthMe | null>(null);
  const [loading, setLoading] = useState(true);

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

  useEffect(() => {
    // Route through the shared, deduped refreshAccessTokenNow() (same helper realtime.ts
    // uses) rather than calling the endpoint directly. React 18 StrictMode double-invokes
    // this effect in dev — and overlapping mounts/timers/tabs can do the same in prod — so
    // without dedup, two concurrent /auth/refresh calls race on the same one-time-use
    // refresh token. It also already clears the access token and notifies
    // authFailureHandler on a definitive 401, so this effect just needs to react to the
    // outcome, not duplicate that bookkeeping.
    let cancelled = false;
    (async () => {
      const token = await refreshAccessTokenNow();
      if (cancelled) return;
      if (!token) {
        // Definitive 401s already cleared user/token via authFailureHandler; transient
        // errors (network down, 5xx) leave the session as-is and just stop loading, so
        // the user sees the sign-in screen without being force-logged-out mid-session.
        setLoading(false);
        return;
      }
      try {
        const me = await api.authMe();
        if (!cancelled) setUser(me);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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
        const login = await api.authLogin({ username, password });
        setAccessToken(login.access_token);
        const me = await api.authMe();
        setUser(me);
      },
      signup: async (username: string, password: string, displayName?: string) => {
        await api.authSignup({ username, password, display_name: displayName });
        const login = await api.authLogin({ username, password });
        setAccessToken(login.access_token);
        const me = await api.authMe();
        setUser(me);
      },
      logout: async () => {
        try {
          await api.authLogout();
        } finally {
          setAccessToken(null);
          setUser(null);
        }
      },
    }),
    [loading, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export { AuthContext };
