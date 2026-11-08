import { Fragment, useState } from "react";

import {
  api,
  type RealisedInstrument,
  type RealisedPeriodQuery,
  type RealisedSale,
  type RealisedTotals,
} from "../lib/api";
import * as fmt from "../lib/format";
import { formatPlatformLabel } from "../lib/platformLabels";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import { DeltaArrow } from "./Delta";
import "./RealisedPnlCard.css";

// #293 (D-78): what selling made or lost, vs what was paid. IBKR's own figure per sale when
// its report has one, else FIFO over the account's buys; a sale with no known cost is named,
// never counted as 0. Markets on Overview is price moves on what you still hold; this is the
// other half. #313: any period (month, year to date, last year, a year), grouped per stock.

const SOURCE_LABEL: Record<string, string> = {
  ibkr: "IBKR's figure",
  fifo: "FIFO from your trades",
  cost_unknown: "cost unknown",
};

type Choice = "month" | "ytd" | "last_year" | "year";

function direction(value: number): "up" | "down" | "flat" {
  return value > 0 ? "up" : value < 0 ? "down" : "flat";
}

function Amount({ value, currency, big = false }: { value: number; currency: string; big?: boolean }) {
  return (
    <span className={`realisedAmount realisedAmount--${direction(value)}${big ? " realisedAmount--big" : ""}`}>
      <DeltaArrow direction={direction(value)} />
      {fmt.formatSignedMoney(value, currency)}
    </span>
  );
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${fmt.formatNumber(count)} ${count === 1 ? one : many}`;
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

function SaleValue({ sale, currency }: { sale: RealisedSale; currency: string }) {
  return (
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
  );
}

function SalesList({ sales, currency, label }: { sales: RealisedSale[]; currency: string; label: string }) {
  return (
    <ul className="realisedSales" aria-label={label}>
      {sales.map((sale, index) => (
        <li key={`${sale.trade_date}-${sale.symbol}-${index}`} className="realisedSale">
          <div className="realisedSaleMain">
            <strong>{sale.symbol ?? "—"}</strong>
            <span className="muted">
              {fmt.formatDate(sale.trade_date)} · {fmt.formatNumber(sale.quantity, 4)} sold
              {sale.cost != null ? ` · cost ${fmt.formatMoney(sale.cost, sale.currency)}` : ""}
            </span>
          </div>
          <SaleValue sale={sale} currency={currency} />
        </li>
      ))}
    </ul>
  );
}

function instrumentNote(row: RealisedInstrument): string | null {
  const parts: string[] = [];
  if (row.cost_unknown) parts.push(`${row.cost_unknown} with no known cost`);
  if (row.fx_missing) parts.push(`no ${row.currency} rate`);
  return parts.length ? `Left out: ${parts.join(", ")}` : null;
}

function ByStock({ rows, currency }: { rows: RealisedInstrument[]; currency: string }) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const gains = rows.reduce((sum, row) => sum + Math.max(row.realised_base, 0), 0);
  const losses = rows.reduce((sum, row) => sum + Math.min(row.realised_base, 0), 0);
  return (
    <div className="realisedByStock">
      <div className="realisedByStockHead">
        <h3 className="realisedSubtitle">By stock</h3>
        <span className="muted realisedSplit">
          Gains <Amount value={gains} currency={currency} /> · Losses <Amount value={losses} currency={currency} />
        </span>
      </div>
      <table className="realisedTable">
        <caption className="srOnly">Realised gain or loss per stock, biggest first</caption>
        <thead>
          <tr>
            <th scope="col">Stock</th>
            <th scope="col" className="num">Sales</th>
            <th scope="col" className="num">Shares sold</th>
            <th scope="col" className="num">Proceeds</th>
            <th scope="col" className="num">Cost</th>
            <th scope="col" className="num">Gain / loss</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const key = `${row.platform}-${row.symbol}-${index}`;
            const open = openKey === key;
            const note = instrumentNote(row);
            return (
              <Fragment key={key}>
                <tr className={`realisedRow${open ? " realisedRow--open" : ""}`}>
                  <th scope="row" className="realisedStockCell">
                    <button
                      type="button"
                      className="realisedStockBtn"
                      aria-expanded={open}
                      aria-label={`${row.symbol ?? "Unknown"}: ${open ? "hide" : "show"} its sales`}
                      onClick={() => setOpenKey(open ? null : key)}
                    >
                      <span className="realisedChevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
                      <span className="realisedStockName">
                        <strong>{row.symbol ?? "—"}</strong>
                        <span className="muted">
                          {row.platform ? formatPlatformLabel(row.platform) : ""}
                          {row.currency !== currency ? ` · ${row.currency}` : ""}
                        </span>
                      </span>
                    </button>
                  </th>
                  <td className="num" data-label="Sales">{fmt.formatNumber(row.sales_count)}</td>
                  <td className="num" data-label="Shares sold">{fmt.formatNumber(row.quantity, 4)}</td>
                  <td className="num" data-label="Proceeds">{row.in_total ? fmt.formatMoney(row.proceeds_base, currency) : "—"}</td>
                  <td className="num" data-label="Cost">{row.in_total ? fmt.formatMoney(row.cost_base, currency) : "—"}</td>
                  <td className="num realisedGainCell" data-label="Gain / loss">
                    {row.in_total ? <Amount value={row.realised_base} currency={currency} /> : <span className="muted">not counted</span>}
                    {note ? <span className="realisedRowNote">{note}</span> : null}
                  </td>
                </tr>
                {open ? (
                  <tr className="realisedDetailRow">
                    <td colSpan={6}>
                      <SalesList sales={row.sales} currency={currency} label={`${row.symbol ?? "Stock"} sales`} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Broker names in this card's notes. Shared labels (platformLabels) stay as they are elsewhere.
function brokerName(platform: string): string {
  return platform.toUpperCase() === "SHAREKHAN" ? "Sharekhan" : formatPlatformLabel(platform);
}

function coverageNote(platforms: string[], tradesFrom: string | null | undefined, periodStart: string | undefined): string[] {
  const out: string[] = [];
  if (tradesFrom && periodStart && periodStart < tradesFrom) {
    out.push(`Trades in the app start on ${fmt.formatDate(tradesFrom)}: earlier sales aren't known yet.`);
  }
  if (platforms.length) {
    const names = platforms.map(brokerName);
    const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0];
    out.push(`${list} ${names.length > 1 ? "report" : "reports"} holdings only, no trades: no realised P&L for ${names.length > 1 ? "them" : "it"}.`);
  }
  return out;
}

export default function RealisedPnlCard({ month, baseCurrency }: { month: string; baseCurrency: string }) {
  const [choice, setChoice] = useState<Choice>("month");
  const [year, setYear] = useState<number | null>(null);
  const [showMonthSales, setShowMonthSales] = useState(false);
  const query: RealisedPeriodQuery | undefined =
    choice === "month" ? undefined : choice === "year" && year != null ? { period: "year", year } : choice === "year" ? undefined : { period: choice };
  const resource = useApiResource(
    resourceKey("realisedPnl", month, baseCurrency, query?.period ?? "month", query?.year ?? ""),
    () => (query ? api.realisedPnl(month, baseCurrency, query) : api.realisedPnl(month, baseCurrency)),
  );
  const data = resource.data;
  if (!data) return null;
  const { month: m, year_to_date: ytd } = data;
  const currency = data.base_currency;
  const monthLabel = fmt.formatMonth(month, "medium");
  const monthYear = month.slice(0, 4);
  const period = data.period_totals ?? m;
  const periodLabel = choice === "month" ? monthLabel : data.period?.label ?? "";
  const rows = data.by_instrument ?? [];
  const years = data.years_with_sales ?? [];
  const notes = coverageNote(data.platforms_without_trades ?? [], data.trades_from, data.period?.start);
  const choose = (next: Choice) => {
    setChoice(next);
    if (next !== "year") setYear(null);
  };
  const stockCount = rows.length;

  const options: { value: Choice; label: string }[] = [
    { value: "month", label: monthLabel },
    { value: "ytd", label: "Year to date" },
    { value: "last_year", label: "Last year" },
  ];

  return (
    <section aria-label="Realised profit and loss">
      <div className="card realisedCard">
        <div className="realisedHeader">
          <div>
            <h2 className="cardTitle">Realised P&amp;L</h2>
            <span className="muted realisedHint">Sales vs what you paid</span>
          </div>
          <div className="realisedPicker">
            <div className="coSegmentedControl" role="group" aria-label="Realised P&L period">
              {options.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={`coSegmentedBtn${choice === option.value ? " coSegmentedBtnActive" : ""}`}
                  aria-pressed={choice === option.value}
                  onClick={() => choose(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <label className="realisedYear">
              <span className="srOnly">Year</span>
              <select
                className="input realisedYearSelect"
                aria-label="Year"
                value={choice === "year" && year != null ? String(year) : ""}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (value) {
                    setYear(value);
                    setChoice("year");
                  } else {
                    choose("month");
                  }
                }}
              >
                <option value="">Year…</option>
                {years.map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="realisedHero" aria-live="polite">
          <span className="realisedPeriodLabel">{periodLabel}</span>
          {period.sales ? (
            <>
              <Amount value={period.realised} currency={currency} big />
              <span className="muted realisedCount">
                {plural(period.sales, "sale")}
                {choice !== "month" && stockCount ? ` · ${plural(stockCount, "stock")}` : ""}
              </span>
            </>
          ) : (
            <span className="muted realisedNone">No sales</span>
          )}
        </div>

        <dl className="realisedTotals">
          <div>
            <dt>{monthLabel}</dt>
            <dd>
              {m.sales ? <Amount value={m.realised} currency={currency} /> : <span className="muted">No sales</span>}
              {m.sales ? <span className="muted realisedCount">{plural(m.sales, "sale")}</span> : null}
            </dd>
          </div>
          <div>
            <dt>{monthYear} to date</dt>
            <dd>
              {ytd.sales ? <Amount value={ytd.realised} currency={currency} /> : <span className="muted">No sales</span>}
              {ytd.sales ? <span className="muted realisedCount">{plural(ytd.sales, "sale")}</span> : null}
            </dd>
          </div>
        </dl>

        {[...caveats(period), ...caveats(ytd)].filter((line, index, all) => all.indexOf(line) === index).map((line) => (
          <p key={line} className="realisedCaveat" role="note">{line}</p>
        ))}
        {/* The month view names the year's sources (as #293 did); a chosen period names its own. */}
        {(() => {
          const from = choice === "month" ? ytd : period;
          return from.sales ? <p className="muted realisedSources">From: {sourcesLine(from)}</p> : null;
        })()}

        {choice !== "month" && rows.length ? <ByStock rows={rows} currency={currency} /> : null}

        {choice === "month" && data.sales.length ? (
          <>
            <button type="button" className="btn realisedToggle" aria-expanded={showMonthSales} onClick={() => setShowMonthSales(!showMonthSales)}>
              {showMonthSales ? "Hide" : "Show"} {monthLabel} sales
            </button>
            {showMonthSales ? <SalesList sales={data.sales} currency={currency} label={`${monthLabel} sales`} /> : null}
          </>
        ) : null}

        {notes.map((line) => (
          <p key={line} className="muted realisedNote">{line}</p>
        ))}
      </div>
    </section>
  );
}

