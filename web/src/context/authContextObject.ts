import { createContext } from "react";
import type { AuthMe } from "../lib/api";

// The context object lives outside AuthContext.tsx so that file exports only its component
// (react-refresh/only-export-components).
export type AuthContextValue = {
  user: AuthMe | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  signup: (username: string, password: string, displayName?: string) => Promise<void>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: false,
  login: async () => {},
  signup: async () => {},
  logout: async () => {},
});
