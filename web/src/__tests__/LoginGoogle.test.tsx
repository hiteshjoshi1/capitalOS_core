import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Login from "../routes/Login";

// #358: the sign-in page shows the methods the API says are on.
const mockAuthMethods = vi.fn();

vi.mock("../context/useAuth", () => ({
  useAuth: () => ({ user: null, loading: false, login: vi.fn(), signup: vi.fn(), logout: vi.fn() }),
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, api: { ...actual.api, authMethods: () => mockAuthMethods() } };
});

function renderLogin(state?: { from: string }) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: "/login", state }]}>
      <Routes>
        <Route path="/login" element={<Login />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Login: Sign in with Google", () => {
  beforeEach(() => {
    mockAuthMethods.mockReset();
  });

  it("shows the Google button first, linking to the API's start with where to go back", async () => {
    mockAuthMethods.mockResolvedValue({ password: true, google: true, signup: false });
    renderLogin({ from: "/cash" });

    const google = await screen.findByRole("link", { name: /sign in with google/i });
    expect(google.getAttribute("href")).toMatch(/\/auth\/google\/start\?next=%2Fcash$/);
    // Password stays as a fallback, after the Google button.
    const password = screen.getByLabelText("Password");
    expect(google.compareDocumentPosition(password) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("or use your password")).toBeInTheDocument();
    // Signup off: no "Create one" link to a page that would refuse.
    expect(screen.queryByText(/create one/i)).not.toBeInTheDocument();
  });

  it("hides the Google button when it isn't set up", async () => {
    mockAuthMethods.mockResolvedValue({ password: true, google: false, signup: true });
    renderLogin();

    await waitFor(() => expect(mockAuthMethods).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: /sign in with google/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign In" })).toBeInTheDocument();
    expect(screen.getByText(/create one/i)).toBeInTheDocument();
  });

  it("shows only Google when password sign-in is turned off", async () => {
    mockAuthMethods.mockResolvedValue({ password: false, google: true, signup: false });
    renderLogin();

    await screen.findByRole("link", { name: /sign in with google/i });
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign In" })).not.toBeInTheDocument();
  });

  it("falls back to the password form when the methods can't be read", async () => {
    mockAuthMethods.mockRejectedValue(new Error("offline"));
    renderLogin();

    await waitFor(() => expect(mockAuthMethods).toHaveBeenCalled());
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /sign in with google/i })).not.toBeInTheDocument();
  });
});
