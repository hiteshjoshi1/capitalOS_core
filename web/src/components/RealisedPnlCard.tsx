import { useState } from "react";

import { api, type RealisedTotals } from "../lib/api";
import * as fmt from "../lib/format";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import { DeltaArrow } from "./Delta";
import "./RealisedPnlCard.css";

// #293 (D-78): what selling made or lost, vs what was paid. IBKR's own figure per sale when
// its report has one, else FIFO over the account's buys; a sale with no known cost is named,
// never counted as 0. Markets on Overview is price moves on what you still hold; this is the
// other half.

const SOURCE_LABEL: Record<string, string> = {
  ibkr: "IBKR's figure",
  fifo: "FIFO from your trades",
  cost_unknown: "cost unknown",
};

function direction(value: number): "up" | "down" | "flat" {
  return value > 0 ? "up" : value < 0 ? "down" : "flat";
}

function Amount({ value, currency }: { value: number; currency: string }) {
  return (
    <span className={`realisedAmount realisedAmount--${direction(value)}`}>
      <DeltaArrow direction={direction(value)} />
      {fmt.formatSignedMoney(value, currency)}
    </span>
  );
}

function caveats(totals: RealisedTotals): string[] {
  const out: string[] = [];
  if (totals.cost_unknown) {
    out.push(`${totals.cost_unknown} sale${totals.cost_unknown === 1 ? "" : "s"} with no known buy cost: left out`);
  }
  if (totals.fx_missing_currencies.length) {
    out.push(`No exchange rate for ${totals.fx_missing_currencies.join(", ")}: left out`);
  }
  return out;
}

function sourcesLine(totals: RealisedTotals): string {
  return Object.entries(totals.sources)
    .filter(([, count]) => count > 0)
    .map(([source, count]) => `${SOURCE_LABEL[source] ?? source} (${count})`)
    .join(" · ");
}

export default function RealisedPnlCard({ month, baseCurrency }: { month: string; baseCurrency: string }) {
  const resource = useApiResource(resourceKey("realisedPnl", month, baseCurrency), () => api.realisedPnl(month, baseCurrency));
  const [open, setOpen] = useState(false);
  const data = resource.data;
  if (!data) return null;
  const { month: m, year_to_date: ytd } = data;
  const currency = data.base_currency;
  const monthLabel = fmt.formatMonth(month, "medium");
  const year = month.slice(0, 4);

  return (
    <section aria-label="Realised profit and loss">
      <div className="card realisedCard">
        <div className="realisedHeader">
          <h2 className="cardTitle">Realised P&amp;L</h2>
          <span className="muted realisedHint">Sales vs what you paid</span>
        </div>
        <dl className="realisedTotals">
          <div>
            <dt>{monthLabel}</dt>
            <dd>
              {m.sales ? <Amount value={m.realised} currency={currency} /> : <span className="muted">No sales</span>}
              {m.sales ? <span className="muted realisedCount">{m.sales} sale{m.sales === 1 ? "" : "s"}</span> : null}
            </dd>
          </div>
          <div>
            <dt>{year} to date</dt>
            <dd>
              {ytd.sales ? <Amount value={ytd.realised} currency={currency} /> : <span className="muted">No sales</span>}
              {ytd.sales ? <span className="muted realisedCount">{ytd.sales} sale{ytd.sales === 1 ? "" : "s"}</span> : null}
            </dd>
          </div>
        </dl>
        {[...caveats(m), ...caveats(ytd).filter((c) => !caveats(m).includes(c))].map((line) => (
          <p key={line} className="realisedCaveat" role="note">{line}</p>
        ))}
        {ytd.sales ? <p className="muted realisedSources">From: {sourcesLine(ytd)}</p> : null}
        {data.sales.length ? (
          <>
            <button type="button" className="btn realisedToggle" aria-expanded={open} onClick={() => setOpen(!open)}>
              {open ? "Hide" : "Show"} {monthLabel} sales
            </button>
            {open ? (
              <ul className="realisedSales">
                {data.sales.map((sale, index) => (
                  <li key={`${sale.trade_date}-${sale.symbol}-${index}`} className="realisedSale">
                    <div className="realisedSaleMain">
                      <strong>{sale.symbol ?? "—"}</strong>
                      <span className="muted">
                        {fmt.formatDate(sale.trade_date)} · {sale.quantity} sold
                      </span>
                    </div>
                    <div className="realisedSaleValue">
                      {sale.realised_base != null ? (
                        <Amount value={sale.realised_base} currency={currency} />
                      ) : sale.realised != null ? (
                        <Amount value={sale.realised} currency={sale.currency} />
                      ) : (
                        <span className="muted">cost unknown</span>
                      )}
                      <span className="muted realisedSaleSource">
                        {SOURCE_LABEL[sale.source] ?? sale.source}
                        {sale.realised != null && sale.currency !== currency ? ` · ${fmt.formatSignedMoney(sale.realised, sale.currency)}` : ""}
                        {sale.fx_missing ? " · no exchange rate" : ""}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}
