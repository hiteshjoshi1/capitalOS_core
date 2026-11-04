import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter, Link, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import LoadError from "../components/LoadError";
import RouteErrorBoundary from "../components/RouteErrorBoundary";

describe("LoadError (#151)", () => {
  it("is announced, says what failed, and retries", () => {
    const onRetry = vi.fn();
    render(<LoadError title="Couldn't load cash" error={new Error("HTTP 500")} onRetry={onRetry} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load cash");
    expect(alert).toHaveTextContent("HTTP 500");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("accepts a string message and no retry", () => {
    render(<LoadError error="offline" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load thisoffline");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("RouteErrorBoundary (#151)", () => {
  afterEach(() => vi.restoreAllMocks());

  function Boom({ when }: { when: boolean }) {
    if (when) throw new Error("render failed");
    return <p>page ok</p>;
  }

  it("contains a render error to the page, and Try again re-renders it", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Harness() {
      const [broken, setBroken] = useState(true);
      return (
        <>
          <nav>sidebar stays</nav>
          <button type="button" onClick={() => setBroken(false)}>
            fix
          </button>
          <RouteErrorBoundary resetKey="/x">
            <Boom when={broken} />
          </RouteErrorBoundary>
        </>
      );
    }
    render(<Harness />);
    expect(screen.getByRole("alert")).toHaveTextContent("This page failed to load");
    expect(screen.getByText("sidebar stays")).toBeInTheDocument();

    fireEvent.click(screen.getByText("fix"));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(screen.getByText("page ok")).toBeInTheDocument();
  });

  it("navigating to another route clears the error", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    // One element for every path (as AppShell's Outlet), so only resetKey can clear it.
    function Page() {
      const path = useLocation().pathname;
      return (
        <>
          <Link to="/fine">go</Link>
          <RouteErrorBoundary resetKey={path}>
            <Boom when={path === "/broken"} />
          </RouteErrorBoundary>
        </>
      );
    }
    render(
      <MemoryRouter initialEntries={["/broken"]}>
        <Routes>
          <Route path="*" element={<Page />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByText("go"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("page ok")).toBeInTheDocument();
  });
});
