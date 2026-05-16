import { useEffect, useState } from "react";

const SELECTED_MONTH_STORAGE_KEY = "capitalos.selectedMonth";
const MONTH_PATTERN = /^\d{4}-\d{2}$/;

export function currentMonthYYYYMM() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function isValidMonth(value: string | null): value is string {
  return value != null && MONTH_PATTERN.test(value);
}

export function readSelectedMonth(storageKey = SELECTED_MONTH_STORAGE_KEY) {
  if (typeof window === "undefined") {
    return currentMonthYYYYMM();
  }

  const storedMonth = window.localStorage.getItem(storageKey);
  return isValidMonth(storedMonth) ? storedMonth : currentMonthYYYYMM();
}

export function useSelectedMonth(storageKey = SELECTED_MONTH_STORAGE_KEY) {
  const [month, setMonth] = useState<string>(() => readSelectedMonth(storageKey));

  useEffect(() => {
    window.localStorage.setItem(storageKey, month);
  }, [month, storageKey]);

  return [month, setMonth] as const;
}
