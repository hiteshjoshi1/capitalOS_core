// Sign-in, sessions and preferences: response and request types (split out of lib/api.ts, #368).

/** GET /auth/methods (#358): which ways of signing in are on. */
export type AuthMethods = {
  password: boolean;
  google: boolean;
  signup: boolean;
};

export type AuthMe = {
  id: number;
  username: string;
  display_name?: string | null;
  email?: string | null;
  is_admin: boolean;
};

export type AuthToken = {
  access_token: string;
  token_type: string;
  expires_in: number;
};

/** /auth/login and /auth/refresh response (#146): the token plus, additively, the user
 * (same shape as /auth/me) and their preferences (same shape as /auth/preferences).
 * Optional: callers fall back to authMe()/getPreferences() when absent. */
export type AuthSession = AuthToken & {
  user?: AuthMe | null;
  preferences?: UserPreferences | null;
};

export type ChangePasswordResult = {
  status: string;
  signed_out_sessions: number;
};

/** Where the effective home timezone comes from (#202): chosen by the user (or filled
 * from their browser), the app's TZ for an account from before #202, or not filled yet. */
export type TimezoneSource = "user" | "app" | "unset";

export type UserPreferences = {
  theme: "dark" | "light";
  accent_color: "#0f7a5c" | "#2b6ddb" | "#8650d9" | "#b5842a";
  /** #202 (additive; absent from older servers). The effective home timezone (IANA name):
   * months, month-end anchors and History follow it. */
  timezone?: string | null;
  timezone_source?: TimezoneSource | null;
  /** #202: the base currency saved on the server; null until set. */
  base_currency?: string | null;
};

export type UserPreferencesPatch = {
  theme?: "dark" | "light";
  accent_color?: "#0f7a5c" | "#2b6ddb" | "#8650d9" | "#b5842a";
  /** IANA timezone name, e.g. "America/New_York" (#202). */
  timezone?: string;
  /** One of CURRENCY_OPTIONS (#202). */
  base_currency?: string;
};
