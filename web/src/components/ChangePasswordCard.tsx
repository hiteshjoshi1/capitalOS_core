import { useState, type FormEvent } from "react";
import { api } from "../lib/api";

// Same bounds as the API (schemas/auth.py).
const MIN_LENGTH = 8;

export default function ChangePasswordCard() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setDone(null);
    if (newPassword !== confirmPassword) {
      setError("The new passwords don't match.");
      return;
    }
    if (newPassword === currentPassword) {
      setError("The new password must be different from the current one.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await api.changePassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      const others = result.signed_out_sessions;
      setDone(
        others > 0
          ? `Password changed. Signed out ${others} other ${others === 1 ? "session" : "sessions"}.`
          : "Password changed.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the password.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card placeholderCard settingsCard" onSubmit={handleSubmit}>
      <div className="cardTitle">Change password</div>
      <p className="muted">Other devices are signed out; this one stays signed in.</p>

      <label className="field">
        <span className="label">Current password</span>
        <input
          className="input"
          type="password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </label>

      <label className="field">
        <span className="label">New password</span>
        <input
          className="input"
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          autoComplete="new-password"
          minLength={MIN_LENGTH}
          required
        />
      </label>

      <label className="field">
        <span className="label">Confirm new password</span>
        <input
          className="input"
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          autoComplete="new-password"
          minLength={MIN_LENGTH}
          required
        />
      </label>

      {error ? <p className="error" role="alert">{error}</p> : null}
      {done ? <p className="muted" role="status">{done}</p> : null}

      <button className="btn settingsThemeToggle" type="submit" disabled={submitting}>
        {submitting ? "Changing…" : "Change password"}
      </button>
    </form>
  );
}
