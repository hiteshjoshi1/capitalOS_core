import { currentAbortSignal } from "../lib/abortScope";

/**
 * A mock API implementation whose replies the test releases one by one (#148 race tests).
 * Each call records its arguments and the abort signal it ran under, so a test can answer
 * a later month first, then the earlier one, and check the page and the aborts.
 */
export function controlledCalls<T>() {
  type Call = {
    args: unknown[];
    signal: AbortSignal | undefined;
    resolve: (value: T) => void;
    reject: (err: unknown) => void;
  };
  const calls: Call[] = [];
  const impl = (...args: unknown[]): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      calls.push({ args, signal: currentAbortSignal(), resolve, reject });
    });
  const find = (match: (args: unknown[]) => boolean): Call => {
    const call = calls.find((c) => match(c.args));
    if (!call) throw new Error(`no call matching; calls: ${JSON.stringify(calls.map((c) => c.args))}`);
    return call;
  };
  return { calls, impl, find };
}

export function monthBefore(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 2, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}
