import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Login from "../routes/Login";
import Signup from "../routes/Signup";

const mockLogin = vi.fn();
const mockSignup = vi.fn();
const mockLogout = vi.fn();

vi.mock("../context/useAuth", () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    login: mockLogin,
    signup: mockSignup,
    logout: mockLogout,
  }),
}));

function renderLogin(initialPath = "/login") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/wealth" element={<div>Home</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function renderSignup(initialPath = "/signup") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/signup" element={<Signup />} />
        <Route path="/wealth" element={<div>Home</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Auth screens", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("submits login credentials", async () => {
    mockLogin.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Username"), "testuser");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("testuser", "password123");
    });
  });

  it("shows login API errors", async () => {
    mockLogin.mockRejectedValueOnce(new Error("API 401: invalid credentials"));
    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Username"), "testuser");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    expect(await screen.findByText(/invalid credentials/i)).toBeInTheDocument();
  });

  it("prevents signup submit when passwords do not match", async () => {
    const user = userEvent.setup();
    renderSignup();

    await user.type(screen.getByLabelText("Username"), "testuser");
    await user.type(screen.getByLabelText("Display Name"), "Test User");
    await user.type(screen.getByLabelText("Password"), "Password123!");
    await user.type(screen.getByLabelText("Confirm Password"), "Mismatch123!");
    await user.click(screen.getByRole("button", { name: "Create Account" }));

    expect(screen.getByText("Passwords do not match.")).toBeInTheDocument();
    expect(mockSignup).not.toHaveBeenCalled();
  });
});
