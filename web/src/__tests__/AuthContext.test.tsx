import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useContext } from "react";
import { AuthProvider } from "../context/AuthContext";
import { AuthContext } from "../context/authContextObject";
import { ThemeProvider, useTheme } from "../context/ThemeContext";

const { mockApi, mockRefreshAccessTokenNow, mockRefreshSessionNow, mockSetAccessToken, mockSetAuthFailureHandler } = vi.hoisted(() => ({
  mockApi: {
    authMe: vi.fn(),
    authLogin: vi.fn(),
    authSignup: vi.fn(),
    authLogout: vi.fn(),
    getPreferences: vi.fn(),
  },
  mockRefreshAccessTokenNow: vi.fn(),
  mockRefreshSessionNow: vi.fn(),
  mockSetAccessToken: vi.fn(),
  mockSetAuthFailureHandler: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: mockApi,
  refreshAccessTokenNow: mockRefreshAccessTokenNow,
  refreshSessionNow: mockRefreshSessionNow,
  setAccessToken: mockSetAccessToken,
  setAuthFailureHandler: mockSetAuthFailureHandler,
}));

function AuthConsumer() {
  const { user, loading, login, signup, logout } = useContext(AuthContext);
  return (
    <div>
      <div data-testid="loading">{String(loading)}</div>
      <div data-testid="user">{user?.username ?? "none"}</div>
      <button onClick={() => void login("alice", "Password123!")}>login</button>
      <button onClick={() => void signup("bob", "Password123!", "Bob")}>signup</button>
      <button onClick={() => void logout()}>logout</button>
    </div>
  );
}

/** A refresh response from a server that predates #146 (token only, no user/preferences). */
function tokenOnlySession(token: string) {
  return { access_token: token, token_type: "bearer", expires_in: 3600 };
}

function renderWithProviders(ui: React.ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

/** The real refreshAccessTokenNow() clears the token and notifies this handler on a
 * definitive 401 (see api.ts callRefreshEndpoint) — grab it so tests can fire that
 * same signal without re-mocking the network layer. */
function capturedAuthFailureHandler(): (() => void) | null {
  const lastCall = mockSetAuthFailureHandler.mock.calls.at(-1);
  return (lastCall?.[0] as (() => void) | undefined) ?? null;
}

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    // Default: getPreferences resolves with defaults (non-fatal if it fails)
    mockApi.getPreferences.mockResolvedValue({ theme: "dark", accent_color: "#0f7a5c" });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("loads session on mount when refresh succeeds", async () => {
    mockRefreshSessionNow.mockResolvedValueOnce(tokenOnlySession("t"));
    mockApi.authMe.mockResolvedValueOnce({ id: 1, username: "demo", is_admin: false });

    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    expect(screen.getByTestId("loading").textContent).toBe("true");
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
      expect(screen.getByTestId("user").textContent).toBe("demo");
    });
    expect(mockRefreshSessionNow).toHaveBeenCalledTimes(1);
  });

  it("does not call authMe when the mount-time refresh fails", async () => {
    mockRefreshSessionNow.mockResolvedValueOnce(null);

    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    expect(mockApi.authMe).not.toHaveBeenCalled();
    expect(screen.getByTestId("user").textContent).toBe("none");
  });

  it("refreshes an active session when the tab becomes visible, deduped through one helper", async () => {
    mockRefreshSessionNow.mockResolvedValueOnce(tokenOnlySession("token"));
    mockRefreshAccessTokenNow.mockResolvedValue("token");
    mockApi.authMe.mockResolvedValueOnce({ id: 1, username: "demo", is_admin: false });

    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("user").textContent).toBe("demo");
    });
    expect(mockRefreshSessionNow).toHaveBeenCalledTimes(1);
    expect(mockRefreshAccessTokenNow).not.toHaveBeenCalled();

    document.dispatchEvent(new Event("visibilitychange"));

    await waitFor(() => {
      expect(mockRefreshAccessTokenNow).toHaveBeenCalledTimes(1);
    });
  });

  it("clears session when the auth-failure handler fires (definitive 401 during background refresh)", async () => {
    mockRefreshSessionNow.mockResolvedValueOnce(tokenOnlySession("token"));
    mockRefreshAccessTokenNow.mockResolvedValue("token");
    mockApi.authMe.mockResolvedValueOnce({ id: 1, username: "demo", is_admin: false });

    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("user").textContent).toBe("demo");
    });

    // Simulate what the real callRefreshEndpoint() does on a definitive 401: it clears
    // the in-memory token itself, then notifies AuthProvider's registered handler.
    capturedAuthFailureHandler()?.();

    await waitFor(() => {
      expect(screen.getByTestId("user").textContent).toBe("none");
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
  });

  it("does not force logout on transient failure during bootstrap", async () => {
    // refreshAccessTokenNow() resolves to null (not a thrown error) for transient
    // failures too — network/5xx errors are swallowed internally and never reach
    // authFailureHandler, so AuthProvider just stops loading without clearing anyone.
    mockRefreshSessionNow.mockResolvedValueOnce(null);

    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
      expect(screen.getByTestId("user").textContent).toBe("none");
    });
    expect(mockSetAccessToken).not.toHaveBeenCalled();
  });

  it("runs login/signup/logout flows and updates user", async () => {
    mockRefreshSessionNow.mockResolvedValueOnce(null);
    mockApi.authMe
      .mockResolvedValueOnce({ id: 11, username: "alice", is_admin: false })
      .mockResolvedValueOnce({ id: 12, username: "bob", is_admin: false });
    mockApi.authLogin
      .mockResolvedValueOnce({ access_token: "login-token", token_type: "bearer", expires_in: 3600 })
      .mockResolvedValueOnce({ access_token: "signup-token", token_type: "bearer", expires_in: 3600 });
    mockApi.authSignup.mockResolvedValueOnce({ id: 12, username: "bob", is_admin: false });
    mockApi.authLogout.mockResolvedValueOnce({ status: "ok" });

    const user = userEvent.setup();
    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await screen.findByText("login");

    await user.click(screen.getByText("login"));
    await waitFor(() => {
      expect(mockApi.authLogin).toHaveBeenCalledWith({ username: "alice", password: "Password123!" });
      expect(screen.getByTestId("user").textContent).toBe("alice");
    });

    await user.click(screen.getByText("signup"));
    await waitFor(() => {
      expect(mockApi.authSignup).toHaveBeenCalledWith({ username: "bob", password: "Password123!", display_name: "Bob" });
      expect(screen.getByTestId("user").textContent).toBe("bob");
    });

    await user.click(screen.getByText("logout"));
    await waitFor(() => {
      expect(mockApi.authLogout).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId("user").textContent).toBe("none");
    });
    expect(mockSetAccessToken).toHaveBeenCalledWith("login-token");
    expect(mockSetAccessToken).toHaveBeenCalledWith("signup-token");
    expect(mockSetAccessToken).toHaveBeenCalledWith(null);
  });

  it("registers and unregisters auth failure handler", async () => {
    mockRefreshSessionNow.mockResolvedValueOnce(null);

    const { unmount } = renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(mockSetAuthFailureHandler).toHaveBeenCalledWith(expect.any(Function));
    });

    unmount();

    expect(mockSetAuthFailureHandler).toHaveBeenLastCalledWith(null);
  });

  it("fetches and applies server preferences after successful auth bootstrap", async () => {
    mockRefreshSessionNow.mockResolvedValueOnce(tokenOnlySession("token"));
    mockApi.authMe.mockResolvedValueOnce({ id: 1, username: "demo", is_admin: false });
    mockApi.getPreferences.mockResolvedValueOnce({ theme: "light", accent_color: "#2b6ddb" });

    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("user").textContent).toBe("demo");
    });

    expect(mockApi.getPreferences).toHaveBeenCalledTimes(1);
  });

  it("handles getPreferences failure gracefully (falls back to localStorage)", async () => {
    mockRefreshSessionNow.mockResolvedValueOnce(tokenOnlySession("token"));
    mockApi.authMe.mockResolvedValueOnce({ id: 1, username: "demo", is_admin: false });
    mockApi.getPreferences.mockRejectedValueOnce(new Error("network error"));

    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
      expect(screen.getByTestId("user").textContent).toBe("demo");
    });
    // Should not throw — preferences failure is non-fatal
  });

  it("logout resets theme/accent to defaults so the next user gets a clean state", async () => {
    // Simulate: user A (light theme) is logged in, then logs out.
    // The theme should reset to dark (default) so user B doesn't inherit user A's theme.
    mockRefreshSessionNow.mockResolvedValueOnce(null);
    mockApi.authLogin.mockResolvedValueOnce({
      access_token: "token-a",
      token_type: "bearer",
      expires_in: 3600,
    });
    mockApi.authMe.mockResolvedValueOnce({ id: 1, username: "user_a", is_admin: false });
    mockApi.getPreferences.mockResolvedValueOnce({ theme: "light", accent_color: "#2b6ddb" });
    mockApi.authLogout.mockResolvedValueOnce({ status: "ok" });

    function ThemeAndAuthConsumer() {
      const { login, logout } = useContext(AuthContext);
      const { theme } = useTheme();
      return (
        <div>
          <div data-testid="theme">{theme}</div>
          <button onClick={() => void login("user_a", "pass")}>login</button>
          <button onClick={() => void logout()}>logout</button>
        </div>
      );
    }

    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <AuthProvider>
          <ThemeAndAuthConsumer />
        </AuthProvider>
      </ThemeProvider>,
    );

    // Log in as user_a (light theme from server)
    await user.click(screen.getByText("login"));
    await waitFor(() => {
      expect(screen.getByTestId("theme").textContent).toBe("light");
    });

    // Log out — theme must reset to default (dark)
    await user.click(screen.getByText("logout"));
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });

    expect(screen.getByTestId("theme").textContent).toBe("dark");
  });

  it("uses user + preferences from the refresh response: no /auth/me or /auth/preferences on cold load (#146)", async () => {
    mockRefreshSessionNow.mockResolvedValueOnce({
      ...tokenOnlySession("token"),
      user: { id: 1, username: "demo", is_admin: false },
      preferences: { theme: "light", accent_color: "#2b6ddb" },
    });

    function ThemeProbe() {
      const { theme, accent } = useTheme();
      return <div data-testid="theme">{`${theme} ${accent}`}</div>;
    }

    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
        <ThemeProbe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("user").textContent).toBe("demo");
    });
    expect(screen.getByTestId("theme").textContent).toBe("light #2b6ddb");
    expect(mockRefreshSessionNow).toHaveBeenCalledTimes(1);
    expect(mockApi.authMe).not.toHaveBeenCalled();
    expect(mockApi.getPreferences).not.toHaveBeenCalled();
  });

  it("does not wait for preferences when the refresh response lacks them", async () => {
    window.localStorage.setItem("capitalos.theme", "dark"); // the stored fallback
    mockRefreshSessionNow.mockResolvedValueOnce({
      ...tokenOnlySession("token"),
      user: { id: 1, username: "demo", is_admin: false },
    });
    let resolvePrefs: (p: { theme: string; accent_color: string }) => void = () => undefined;
    mockApi.getPreferences.mockReturnValueOnce(
      new Promise((resolve) => {
        resolvePrefs = resolve;
      }),
    );

    function ThemeProbe() {
      const { theme } = useTheme();
      return <div data-testid="theme">{theme}</div>;
    }

    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
        <ThemeProbe />
      </AuthProvider>,
    );

    // Signed in and rendering while preferences are still pending.
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
      expect(screen.getByTestId("user").textContent).toBe("demo");
    });
    expect(screen.getByTestId("theme").textContent).toBe("dark");

    await act(async () => {
      resolvePrefs({ theme: "light", accent_color: "#2b6ddb" });
    });
    expect(screen.getByTestId("theme").textContent).toBe("light");
  });

  it("login uses user + preferences from the login response", async () => {
    mockRefreshSessionNow.mockResolvedValueOnce(null);
    mockApi.authLogin.mockResolvedValueOnce({
      ...tokenOnlySession("login-token"),
      user: { id: 11, username: "alice", is_admin: false },
      preferences: { theme: "light", accent_color: "#8650d9" },
    });

    const user = userEvent.setup();
    renderWithProviders(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );
    await user.click(await screen.findByText("login"));
    await waitFor(() => {
      expect(screen.getByTestId("user").textContent).toBe("alice");
    });
    expect(mockApi.authMe).not.toHaveBeenCalled();
    expect(mockApi.getPreferences).not.toHaveBeenCalled();
    expect(mockSetAccessToken).toHaveBeenCalledWith("login-token");
  });
});
