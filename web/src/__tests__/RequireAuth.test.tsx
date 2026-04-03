import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import RequireAuth from "../components/RequireAuth";

const mockUseAuth = vi.fn();

vi.mock("../context/useAuth", () => ({
  useAuth: () => mockUseAuth(),
}));

function LoginProbe() {
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "";
  return <div>login:{from}</div>;
}

describe("RequireAuth", () => {
  it("renders loading state while auth is resolving", () => {
    mockUseAuth.mockReturnValue({ user: null, loading: true });
    render(
      <MemoryRouter initialEntries={["/private"]}>
        <Routes>
          <Route element={<RequireAuth />}>
            <Route path="/private" element={<div>private</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Loading session…")).toBeInTheDocument();
  });

  it("redirects anonymous users to login with source path", () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false });
    render(
      <MemoryRouter initialEntries={["/private"]}>
        <Routes>
          <Route path="/login" element={<LoginProbe />} />
          <Route element={<RequireAuth />}>
            <Route path="/private" element={<div>private</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("login:/private")).toBeInTheDocument();
  });

  it("renders protected outlet for authenticated user", () => {
    mockUseAuth.mockReturnValue({ user: { id: 1, username: "demo" }, loading: false });
    render(
      <MemoryRouter initialEntries={["/private"]}>
        <Routes>
          <Route element={<RequireAuth />}>
            <Route path="/private" element={<div>private</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("private")).toBeInTheDocument();
  });
});

