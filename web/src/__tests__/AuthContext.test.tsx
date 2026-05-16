import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useContext } from "react";
import { AuthContext, AuthProvider } from "../context/AuthContext";

const { mockApi, mockSetAccessToken, mockSetAuthFailureHandler, MockAuthExpiredError } = vi.hoisted(() => {
  class _MockAuthExpiredError extends Error {
    constructor(msg = "Session expired") {
      super(msg);
      this.name = "AuthSessionExpiredError";
    }
  }
  return {
    mockApi: {
      authRefresh: vi.fn(),
      authMe: vi.fn(),
      authLogin: vi.fn(),
      authSignup: vi.fn(),
      authLogout: vi.fn(),
    },
    mockSetAccessToken: vi.fn(),
    mockSetAuthFailureHandler: vi.fn(),
    MockAuthExpiredError: _MockAuthExpiredError,
  };
});

vi.mock("../lib/api", () => ({
  api: mockApi,
  setAccessToken: mockSetAccessToken,
  setAuthFailureHandler: mockSetAuthFailureHandler,
  AuthSessionExpiredError: MockAuthExpiredError,
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

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("loads session on mount when refresh succeeds", async () => {
    mockApi.authRefresh.mockResolvedValueOnce({ access_token: "t", token_type: "bearer", expires_in: 3600 });
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
    expect(mockSetAccessToken).toHaveBeenCalledWith("t");
  });

  it("refreshes an active session when the tab becomes visible", async () => {
    mockApi.authRefresh
      .mockResolvedValueOnce({ access_token: "initial", token_type: "bearer", expires_in: 3600 })
      .mockResolvedValueOnce({ access_token: "rotated", token_type: "bearer", expires_in: 3600 });
    mockApi.authMe.mockResolvedValueOnce({ id: 1, username: "demo", is_admin: false });

    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("user").textContent).toBe("demo");
    });

    document.dispatchEvent(new Event("visibilitychange"));

    await waitFor(() => {
      expect(mockSetAccessToken).toHaveBeenCalledWith("rotated");
    });
  });

  it("clears session on definitive auth failure (AuthSessionExpiredError) during bootstrap", async () => {
    mockApi.authRefresh.mockRejectedValueOnce(new MockAuthExpiredError("Session expired"));

    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
      expect(screen.getByTestId("user").textContent).toBe("none");
    });
    expect(mockSetAccessToken).toHaveBeenCalledWith(null);
    expect(mockSetAuthFailureHandler).toHaveBeenCalled();
  });

  it("does not force logout on transient network error during bootstrap", async () => {
    mockApi.authRefresh.mockRejectedValueOnce(new Error("Unable to reach API at http://localhost:8000: Failed to fetch"));

    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
      expect(screen.getByTestId("user").textContent).toBe("none");
    });
    // setAccessToken should NOT be called with null on a transient error
    expect(mockSetAccessToken).not.toHaveBeenCalledWith(null);
  });

  it("runs login/signup/logout flows and updates user", async () => {
    mockApi.authRefresh.mockResolvedValueOnce({ access_token: "initial", token_type: "bearer", expires_in: 3600 });
    mockApi.authMe
      .mockResolvedValueOnce({ id: 10, username: "seed", is_admin: false })
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
    mockApi.authRefresh.mockRejectedValueOnce(new MockAuthExpiredError("Session expired"));

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
