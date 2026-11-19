import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import RedirectKeepingSearch from "../components/RedirectKeepingSearch";

function Where() {
  const { pathname, search, hash } = useLocation();
  return <div data-testid="where">{`${pathname}${search}${hash}`}</div>;
}

describe("RedirectKeepingSearch (#450)", () => {
  it.each(["/liabilities", "/credit-cards"])("sends %s to /cards with its query string", (from) => {
    render(
      <MemoryRouter initialEntries={[`${from}?card=12#due`]}>
        <Routes>
          <Route path={from} element={<RedirectKeepingSearch to="/cards" />} />
          <Route path="/cards" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("where")).toHaveTextContent("/cards?card=12#due");
  });
});
