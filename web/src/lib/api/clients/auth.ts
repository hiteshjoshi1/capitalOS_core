// Sign-in, sessions and preferences: API calls (split out of lib/api.ts, #368).
import { getAccessToken, req } from "../http";
import type { AuthMe, AuthMethods, AuthSession, ChangePasswordResult, UserPreferences, UserPreferencesPatch } from "../types/auth";

export const authClient = {
  /** Returns true when there is an in-memory access token (user is logged in). */
  isAuthenticated: (): boolean => Boolean(getAccessToken()),
  authSignup: (payload: { username: string; password: string; display_name?: string }) =>
    req<AuthMe>("/auth/signup", { method: "POST", body: JSON.stringify(payload) }, { skipAuth: true }),
  authLogin: (payload: { username: string; password: string }) =>
    req<AuthSession>("/auth/login", { method: "POST", body: JSON.stringify(payload) }, { skipAuth: true }),
  authRefresh: () =>
    req<AuthSession>("/auth/refresh", { method: "POST" }, { skipAuth: true, skipRefreshRetry: true }),
  authMe: () => req<AuthMe>("/auth/me"),
  authMethods: () => req<AuthMethods>("/auth/methods", undefined, { skipAuth: true, skipRefreshRetry: true }),
  authLogout: () => req<{ status: string }>("/auth/logout", { method: "POST" }),
  changePassword: (payload: { current_password: string; new_password: string }) =>
    req<ChangePasswordResult>("/auth/change-password", { method: "POST", body: JSON.stringify(payload) }),
  getPreferences: () => req<UserPreferences>("/auth/preferences"),
  patchPreferences: (patch: UserPreferencesPatch) =>
    req<UserPreferences>("/auth/preferences", { method: "PATCH", body: JSON.stringify(patch) }),
};
