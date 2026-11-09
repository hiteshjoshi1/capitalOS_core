import { useState } from "react";
import { api } from "../lib/api";
import type { MarketDataTickerTest, MarketDataUnpricedItem } from "../lib/api";
import * as fmt from "../lib/format";

const REASONS: Record<string, string> = {
  no_asset: "Not linked to a stock yet: it can't be given a ticker here",
  no_symbol: "No ticker on a configured exchange",
  no_quote: "Yahoo has no quote for its ticker",
};

/** One unpriced holding with "Set ticker" (#320): type a Yahoo symbol (or pick a suggestion),
 * test it (the latest close Yahoo has), then save it as the holding's override. Admins only. */
function NeedsFixRow({
  item,
  canFix,
  onSaved,
}: {
  item: MarketDataUnpricedItem;
  canFix: boolean;
  onSaved: (message: string) => void;
}) {
  const [symbol, setSymbol] = useState<string>(item.suggested_yahoo_symbols[1] ?? item.suggested_yahoo_symbols[0] ?? "");
  const [tested, setTested] = useState<MarketDataTickerTest | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [error, setError] = useState<string>("");
  const label = item.symbol || item.name || "A holding";
  const fixable = canFix && item.asset_id != null && !!item.exchange_code;
  const testedOk = tested?.found === true && tested.yahoo_symbol === symbol.trim().toUpperCase();

  async function onTest() {
    setBusy("test");
    setError("");
    try {
      setTested(await api.marketDataTickerTest(symbol.trim(), item.exchange_code));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function onSave() {
    if (item.asset_id == null || !item.exchange_code) return;
    setBusy("save");
    setError("");
    try {
      const saved = await api.marketDataSetTicker(item.asset_id, item.exchange_code, symbol.trim());
      onSaved(`${label} now uses ${saved.yahoo_symbol}: ${fmt.formatMoney(saved.close ?? null, saved.currency)} on ${fmt.formatDate(saved.trade_date ?? null)}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="needsFixRow" data-testid={`needs-fix-${label}`}>
      <div className="needsFixWhat">
        <strong>{label}</strong>
        {item.name && item.name !== label ? <span className="muted"> {item.name}</span> : null}
        <div className="muted needsFixMeta">
          {[item.platform, item.exchange_code].filter(Boolean).join(" · ")} · {REASONS[item.reason] ?? item.reason}
        </div>
      </div>
      {fixable ? (
        <div className="needsFixAction">
          <label className="needsFixField">
            <span className="srOnly">Yahoo ticker for {label}</span>
            <input
              className="input"
              value={symbol}
              placeholder="e.g. CODE.BO"
              aria-label={`Yahoo ticker for ${label}`}
              onChange={(e) => {
                setSymbol(e.target.value.toUpperCase());
                setTested(null);
              }}
            />
          </label>
          {item.suggested_yahoo_symbols.length > 0 && (
            <div className="needsFixSuggestions" role="group" aria-label="Suggested tickers">
              {item.suggested_yahoo_symbols.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="ccFilterPill"
                  aria-pressed={symbol === s}
                  onClick={() => {
                    setSymbol(s);
                    setTested(null);
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          <div className="needsFixButtons">
            <button type="button" className="btn btnSmall" disabled={!symbol.trim() || busy !== null} onClick={onTest}>
              {busy === "test" ? "Testing…" : "Test"}
            </button>
            <button
              type="button"
              className="btn btnSmall btnPrimary"
              disabled={!testedOk || busy !== null}
              title={testedOk ? undefined : "Test the ticker first"}
              onClick={onSave}
            >
              {busy === "save" ? "Saving…" : "Save ticker"}
            </button>
          </div>
          {tested && (
            <p className={tested.found ? "needsFixResult" : "needsFixResult needsFixResultBad"} role="status">
              {tested.found
                ? `${tested.yahoo_symbol}: ${fmt.formatMoney(tested.close ?? null, tested.currency)} on ${fmt.formatDate(tested.trade_date ?? null)}`
                : tested.error ?? `Yahoo has no quote for ${tested.yahoo_symbol}`}
            </p>
          )}
          {error && <p className="hint" role="alert">{error}</p>}
        </div>
      ) : (
        <p className="muted needsFixAction">
          {item.asset_id == null ? "Link it to a stock first." : canFix ? "" : "An admin can set its ticker."}
        </p>
      )}
    </li>
  );
}

/** Market data's "Needs a fix" list (#320): held stocks the refresh can't price. */
export default function MarketDataNeedsFix({
  items,
  canFix,
  onSaved,
}: {
  items: MarketDataUnpricedItem[];
  canFix: boolean;
  onSaved: (message: string) => void;
}) {
  if (items.length === 0) {
    return <p className="muted">Every holding has a price.</p>;
  }
  return (
    <ul className="needsFixList">
      {items.map((item) => (
        <NeedsFixRow key={`${item.instrument_id}-${item.exchange_code}`} item={item} canFix={canFix} onSaved={onSaved} />
      ))}
    </ul>
  );
}
