import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Companies from "../routes/Companies";

describe("Companies", () => {
  it("renders the coming-soon hero and disabled CTA", () => {
    render(
      <MemoryRouter>
        <Companies />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Companies" })).toBeInTheDocument();
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Companies — Coming Soon/i })).toBeDisabled();
  });

  it("renders the non-interactive preview cards", () => {
    render(
      <MemoryRouter>
        <Companies />
      </MemoryRouter>,
    );

    expect(screen.getByText("What's planned")).toBeInTheDocument();
    expect(screen.getByText("DBS Group Holdings")).toBeInTheDocument();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("Sea Limited")).toBeInTheDocument();
  });
});
