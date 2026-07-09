import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useContext } from "react";
import { AuthContext, AuthProvider } from "../context/AuthContext";

const { mockApi, mockRefreshAccessTokenNow, mockSetAccessToken, mockSetAuthFailureHandler } = vi.hoisted(() => ({
  mockApi: {
    authMe: vi.fn(),
    authLogin: vi.fn(),
    authSignup: vi.fn(),
    authLogout: vi.fn(),
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
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("loads session on mount when refresh succeeds", async () => {
    mockRefreshAccessTokenNow.mockResolvedValueOnce("t");
    mockApi.authMe.mockResolvedValueOnce({ id: 1, username: "demo", is_admin: false });

    render(
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

    render(
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

    render(
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

    render(
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

    render(
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
    render(
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

    const { unmount } = render(
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
});
