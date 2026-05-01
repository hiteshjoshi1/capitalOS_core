import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import App from "../App";

describe("App route redirect", () => {
  it("sends the shell root to Wealth Overview", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<App />} />
          <Route path="/wealth" element={<div>Wealth Overview Landing</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Wealth Overview Landing")).toBeInTheDocument();
  });
});
