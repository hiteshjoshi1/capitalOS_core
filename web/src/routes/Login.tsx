import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/useAuth";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (user) {
    return <Navigate to="/wealth" replace />;
  }

  const from = (location.state as { from?: string } | null)?.from || "/wealth";

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
        <p className="muted authSubtitle">Use your CapitalOS username and password.</p>

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

        <button className="btn btnLarge" type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign In"}
        </button>

        <p className="muted authFooter">
          No account yet? <Link to="/signup">Create one</Link>
        </p>
      </form>
    </div>
  );
}
