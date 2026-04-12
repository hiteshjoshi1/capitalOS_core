import { createContext, useEffect, useMemo, useState } from "react";
import { api, setAccessToken, setAuthFailureHandler, AuthSessionExpiredError } from "../lib/api";
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
    let cancelled = false;
    (async () => {
      try {
        await api.authRefresh();
        const me = await api.authMe();
        if (cancelled) return;
        setUser(me);
      } catch (err) {
        if (!cancelled) {
          if (err instanceof AuthSessionExpiredError) {
            // Definitively invalid session: clear token and treat as signed out.
            setAccessToken(null);
            setUser(null);
          }
          // Transient errors (network down, 5xx): access token is already null on reload,
          // just finish loading. The user will see the sign-in screen but was not force-logged out.
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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
