import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import App from "./App";

describe("App", () => {
  it("redirects the root route to Wealth", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<App />} />
          <Route path="/wealth" element={<div>Wealth landing</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Wealth landing")).toBeInTheDocument();
  });
});
