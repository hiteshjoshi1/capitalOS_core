import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { WealthTimelinePoint, WealthTopMovers } from "../lib/api";
import { currentMonthYYYYMM } from "../lib/selectedMonth";
import type { ComponentDeltas, MonthFlags } from "../lib/wealthHistoryAnalysis";
import * as fmt from "../lib/format";

type LoadState = "idle" | "loading" | "ready" | "error";

type Props = {
  month: string;
  point: WealthTimelinePoint;
  prevPoint: WealthTimelinePoint | null;
  flags: MonthFlags;
  baseCurrency: string;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
  onClose: () => void;
};

const COMPONENT_LABEL: Record<keyof ComponentDeltas, string> = {
  stocks_funds: "Stocks & funds",
  cash: "Cash",
  crypto: "Crypto",
  liabilities: "Liabilities",
};

const COMPONENT_COLOR: Record<keyof ComponentDeltas, string> = {
  stocks_funds: "var(--wh-stocks)",
  cash: "var(--wh-cash)",
  crypto: "var(--wh-crypto)",
  liabilities: "var(--muted)",
};

function monthLongLabel(month: string): string {
  return fmt.formatMonth(month);
}

function assetClassMatchesComponent(assetClass: string, dominant: string | null): boolean {
  if (!dominant) return true;
  const upper = assetClass.toUpperCase();
  if (dominant === "stocks_funds") return upper === "STOCK" || upper === "FUND";
  if (dominant === "crypto") return upper === "CRYPTO";
  return true;
}

export default function WealthDrilldownPanel({ month, point, prevPoint, flags, baseCurrency, formatMoney, onClose }: Props) {
  // #151: opening the panel moves focus to its heading (so keyboard and screen-reader
  // users land on what they asked for); closing returns focus to where it came from.
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      if (opener && opener.isConnected) opener.focus();
    };
  }, []);
  useEffect(() => {
    headingRef.current?.focus();
  }, [month]);

  const [moversState, setMoversState] = useState<LoadState>("idle");
  const [movers, setMovers] = useState<WealthTopMovers | null>(null);

  const [contextState, setContextState] = useState<LoadState>("idle");
  const [dividends, setDividends] = useState<number | null>(null);
  const [netCashFlow, setNetCashFlow] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setMoversState("loading");
      try {
        const data = await api.netWorthTimelineMovers(month, baseCurrency, 8);
        if (!cancelled) {
          setMovers(data);
          setMoversState("ready");
        }
      } catch {
        if (!cancelled) setMoversState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [month, baseCurrency]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setContextState("loading");
      try {
        const [divData, spendData] = await Promise.all([
          api.dividendsSummary(month, month, "month", baseCurrency),
          api.spendingSummary(month, baseCurrency),
        ]);
        if (!cancelled) {
          setDividends(divData.buckets[0]?.net_received ?? 0);
          setNetCashFlow(spendData.net);
          setContextState("ready");
        }
      } catch {
        if (!cancelled) setContextState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [month, baseCurrency]);

  const delta = flags.delta;
  const pct = delta != null && prevPoint && prevPoint.total !== 0 ? (delta / prevPoint.total) * 100 : null;
  const showSnapshotClockCaveat = month === currentMonthYYYYMM() && point.uploads.length > 0;

  const filteredMovers = movers
    ? {
        gainers: movers.gainers.filter((m) => assetClassMatchesComponent(m.asset_class, flags.dominantComponent)),
        detractors: movers.detractors.filter((m) => assetClassMatchesComponent(m.asset_class, flags.dominantComponent)),
      }
    : null;
  const moversToShow =
    filteredMovers && (filteredMovers.gainers.length > 0 || filteredMovers.detractors.length > 0)
      ? filteredMovers
      : movers;

  return (
    <aside
      className="whDrillPanel"
      aria-label={`Details for ${monthLongLabel(month)}`}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="whDrillHead">
        <h3 ref={headingRef} tabIndex={-1}>
          {monthLongLabel(month)}
        </h3>
        <button type="button" className="whDrillClose" onClick={onClose} aria-label="Close details">
          ×
        </button>
      </div>

      {showSnapshotClockCaveat ? (
        <div className="whDrillBanner">
          Uses data through {fmt.formatDate(point.anchor_date)}; recent uploads apply next month.
        </div>
      ) : null}

      {delta == null ? (
        <p className="muted">Start of available history.</p>
      ) : (
        <>
          <div className={`whDrillDelta ${delta >= 0 ? "wealthTrendPositive" : "wealthTrendNegative"}`}>
            {fmt.formatSignedMoney(delta, baseCurrency)}
          </div>
          <div className="whDrillPct">
            {fmt.formatPercent(pct, { signed: true, scale: "points" })}
            {flags.comparedToMonth ? ` vs ${monthLongLabel(flags.comparedToMonth)}` : ""}
          </div>

          {flags.isOutlier ? (
            <div className="whDrillBanner">
              ⚠ Unusual move{flags.dominantComponent ? ` — driven by ${COMPONENT_LABEL[flags.dominantComponent]}` : ""}
            </div>
          ) : null}
          {flags.isCatchUp ? (
            <div className="whDrillBanner">
              ⚠ Catch-up month — a source uploaded after a gap. This delta includes drift accrued since the last
              upload.
            </div>
          ) : null}
          {flags.componentDeltas ? (
            <div className="whWaterfall">
              {(Object.keys(flags.componentDeltas) as (keyof ComponentDeltas)[]).map((key) => {
                const v = key === "liabilities" ? -flags.componentDeltas![key] : flags.componentDeltas![key];
                const maxAbs = Math.max(
                  ...Object.entries(flags.componentDeltas!).map(([k, val]) => Math.abs(k === "liabilities" ? -val : val)),
                  1,
                );
                const widthPct = (Math.abs(v) / maxAbs) * 48;
                return (
                  <div className="whWfRow" key={key}>
                    <span className="whWfLabel">{COMPONENT_LABEL[key]}</span>
                    <div className="whWfTrack">
                      <div
                        className="whWfBar"
                        style={{
                          width: `${widthPct}%`,
                          left: v >= 0 ? "50%" : `${50 - widthPct}%`,
                          background: COMPONENT_COLOR[key],
                        }}
                      />
                    </div>
                    <span className={`whWfVal ${v >= 0 ? "wealthTrendPositive" : "wealthTrendNegative"}`}>
                      {fmt.formatSignedMoney(v, baseCurrency)}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : null}

          <div className="whDrillSection">
            <h4>TOP MOVERS{flags.dominantComponent ? ` — ${COMPONENT_LABEL[flags.dominantComponent].toUpperCase()}` : ""}</h4>
            {moversState === "loading" ? (
              <p className="muted" role="status">Loading…</p>
            ) : moversToShow && (moversToShow.gainers.length > 0 || moversToShow.detractors.length > 0) ? (
              [...moversToShow.gainers, ...moversToShow.detractors]
                .sort((a, b) => Math.abs(b.delta_abs) - Math.abs(a.delta_abs))
                .slice(0, 5)
                .map((m) => (
                  <div className="whMoverRow" key={`${m.asset_class}-${m.symbol}`}>
                    <span>
                      <strong>{m.symbol}</strong> <span className="whMoverClass">{m.asset_class}</span>
                    </span>
                    <span className={m.delta_abs >= 0 ? "wealthTrendPositive" : "wealthTrendNegative"}>
                      {fmt.formatDelta(m.delta_abs, m.delta_pct, baseCurrency)}
                    </span>
                  </div>
                ))
            ) : (
              <p className="muted">No significant individual movers.</p>
            )}
          </div>

          <div className="whDrillSection">
            <h4>THAT MONTH</h4>
            {contextState === "loading" ? (
              <p className="muted" role="status">Loading…</p>
            ) : (
              <>
                <div className="whContextRow">
                  <span>Dividends received</span>
                  <strong>{dividends != null ? formatMoney(dividends) : "—"}</strong>
                </div>
                <div className="whContextRow">
                  <span>Net cash flow</span>
                  <strong>{netCashFlow != null ? formatMoney(netCashFlow) : "—"}</strong>
                </div>
                <div className="whContextRow">
                  <span>Uploads landed</span>
                  <strong>{point.uploads.length > 0 ? point.uploads.join(", ") : "none"}</strong>
                </div>
              </>
            )}
            <Link className="wealthInlineLink" to="/cash-flow">
              Open cash flow for this period →
            </Link>
          </div>
        </>
      )}
    </aside>
  );
}
