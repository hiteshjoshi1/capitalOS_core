import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/useAuth";
import { api, googleSignInUrl } from "../lib/api";
import type { AuthMethods } from "../lib/api";

/** Until /auth/methods answers (or if it can't): the password form, as before #358. */
const FALLBACK_METHODS: AuthMethods = { password: true, google: false, signup: true };

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [methods, setMethods] = useState<AuthMethods | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .authMethods()
      .then((m) => {
        if (!cancelled) setMethods(m);
      })
      .catch(() => {
        if (!cancelled) setMethods(FALLBACK_METHODS);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (user) {
    return <Navigate to="/wealth" replace />;
  }

  const from = (location.state as { from?: string } | null)?.from || "/wealth";
  const shown = methods ?? FALLBACK_METHODS;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="authPage">
      <form className="card authCard" onSubmit={handleSubmit}>
        <h1 className="authTitle">Sign In</h1>

        {/* #358: Google first; a full-page navigation, the API does the OAuth exchange. */}
        {shown.google ? (
          <a className="btn btnLarge authGoogleBtn" href={googleSignInUrl(from)}>
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48">
              <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.4 30.2 0 24 0 14.6 0 6.6 5.4 2.7 13.3l7.8 6C12.4 13.7 17.7 9.5 24 9.5z" />
              <path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.4 5.7c4.3-4 6.9-9.9 6.9-17.1z" />
              <path fill="#FBBC05" d="M10.5 28.7c-.5-1.4-.8-3-.8-4.7s.3-3.2.8-4.7l-7.8-6C1 16.6 0 20.2 0 24s1 7.4 2.7 10.7l7.8-6z" />
              <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.4-5.7c-2.1 1.4-4.8 2.2-8.5 2.2-6.3 0-11.6-4.2-13.5-9.9l-7.8 6C6.6 42.6 14.6 48 24 48z" />
            </svg>
            Sign in with Google
          </a>
        ) : null}

        {shown.google && shown.password ? <p className="muted authDivider">or use your password</p> : null}

        {shown.password ? (
          <>
            {!shown.google ? <p className="muted authSubtitle">Use your CapitalOS username and password.</p> : null}
            <label className="field">
              <span className="label">Username</span>
              <input
                className="input"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
              />
            </label>

            <label className="field">
              <span className="label">Password</span>
              <input
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                minLength={8}
                required
              />
            </label>

            {error ? <p className="error">{error}</p> : null}

            <button className={shown.google ? "btn" : "btn btnLarge"} type="submit" disabled={submitting}>
              {submitting ? "Signing in…" : "Sign In"}
            </button>
          </>
        ) : null}

        {shown.signup ? (
          <p className="muted authFooter">
            No account yet? <Link to="/signup">Create one</Link>
          </p>
        ) : null}
      </form>
    </div>
  );
}
