import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "../context/ThemeContext";
import AppShell from "../components/AppShell";

vi.mock("../lib/api", () => ({
  api: {
    uploadReminderCount: vi.fn().mockResolvedValue({ count: 0 }),
  },
}));

describe("AppShell", () => {
  it("renders sidebar alongside outlet content", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<div>Dashboard Content</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    // Sidebar present (aside = complementary role)
    expect(screen.getByRole("complementary", { name: "Main navigation" })).toBeInTheDocument();

    // Outlet content rendered
    expect(screen.getByText("Dashboard Content")).toBeInTheDocument();
  });

  it("renders sidebar nav with Dashboard link", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<div>Content</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("renders content inside appShellMain alongside sidebar", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/some-page"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/some-page" element={<div data-testid="page-content">Page</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByTestId("page-content")).toBeInTheDocument();
    const main = screen.getByRole("main");
    expect(main).toBeInTheDocument();
    expect(main).toContainElement(screen.getByTestId("page-content"));
  });
});
