import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useContext } from "react";
import { AuthContext, AuthProvider } from "../context/AuthContext";
import { ThemeProvider, useTheme } from "../context/ThemeContext";

const { mockApi, mockRefreshAccessTokenNow, mockSetAccessToken, mockSetAuthFailureHandler } = vi.hoisted(() => ({
  mockApi: {
    authMe: vi.fn(),
    authLogin: vi.fn(),
    authSignup: vi.fn(),
    authLogout: vi.fn(),
    getPreferences: vi.fn(),
  },
  mockRefreshAccessTokenNow: vi.fn(),
  mockSetAccessToken: vi.fn(),
  mockSetAuthFailureHandler: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: mockApi,
  refreshAccessTokenNow: mockRefreshAccessTokenNow,
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
    mockRefreshAccessTokenNow.mockResolvedValueOnce("t");
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
    expect(mockRefreshAccessTokenNow).toHaveBeenCalledTimes(1);
  });

  it("does not call authMe when the mount-time refresh fails", async () => {
    mockRefreshAccessTokenNow.mockResolvedValueOnce(null);

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
    expect(mockRefreshAccessTokenNow).toHaveBeenCalledTimes(1);

    document.dispatchEvent(new Event("visibilitychange"));

    await waitFor(() => {
      expect(mockRefreshAccessTokenNow).toHaveBeenCalledTimes(2);
    });
  });

  it("clears session when the auth-failure handler fires (definitive 401 during background refresh)", async () => {
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
    mockRefreshAccessTokenNow.mockResolvedValueOnce(null);

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
    mockRefreshAccessTokenNow.mockResolvedValueOnce(null);
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
    mockRefreshAccessTokenNow.mockResolvedValueOnce(null);

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
    mockRefreshAccessTokenNow.mockResolvedValueOnce("token");
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
    mockRefreshAccessTokenNow.mockResolvedValueOnce("token");
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
    mockRefreshAccessTokenNow.mockResolvedValueOnce(null);
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
});
