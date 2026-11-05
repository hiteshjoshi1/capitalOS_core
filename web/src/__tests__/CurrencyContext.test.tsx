import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import BaseCurrencyPicker from "../components/BaseCurrencyPicker";
import { BASE_CURRENCY_STORAGE_KEY, setBaseCurrency, useBaseCurrency } from "../context/CurrencyContext";
import { CURRENCY_OPTIONS } from "../lib/format";

function Reader({ label }: { label: string }) {
  const [ccy] = useBaseCurrency();
  return <span>{`${label}:${ccy}`}</span>;
}

describe("shared base currency (#150)", () => {
  it("defaults to SGD and offers the one option list", () => {
    render(<BaseCurrencyPicker />);
    const select = screen.getByLabelText("Base currency") as HTMLSelectElement;
    expect(select.value).toBe("SGD");
    expect([...select.options].map((o) => o.value)).toEqual([...CURRENCY_OPTIONS]);
  });

  it("a change in the header picker reaches every page at once", () => {
    render(
      <>
        <BaseCurrencyPicker />
        <Reader label="stocks" />
        <Reader label="cash" />
      </>,
    );
    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "HKD" } });
    expect(screen.getByText("stocks:HKD")).toBeInTheDocument();
    expect(screen.getByText("cash:HKD")).toBeInTheDocument();
  });

  it("survives navigation and reload (stored per browser)", () => {
    const first = render(<BaseCurrencyPicker />);
    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "USD" } });
    expect(window.localStorage.getItem(BASE_CURRENCY_STORAGE_KEY)).toBe("USD");
    first.unmount();
    // A fresh mount (another page, or the app after a reload) reads the stored value.
    render(<Reader label="after" />);
    expect(screen.getByText("after:USD")).toBeInTheDocument();
  });

  it("ignores unknown or tampered values", () => {
    window.localStorage.setItem(BASE_CURRENCY_STORAGE_KEY, "XYZ");
    render(<Reader label="r" />);
    expect(screen.getByText("r:SGD")).toBeInTheDocument();
    act(() => setBaseCurrency("EUR"));
    expect(screen.getByText("r:SGD")).toBeInTheDocument();
  });

  it("follows a change made in another tab", () => {
    render(<Reader label="tab" />);
    act(() => {
      window.localStorage.setItem(BASE_CURRENCY_STORAGE_KEY, "INR");
      window.dispatchEvent(new StorageEvent("storage", { key: BASE_CURRENCY_STORAGE_KEY }));
    });
    expect(screen.getByText("tab:INR")).toBeInTheDocument();
  });
});
