// #417 (U17, D-117): the dividends current holdings are expected to pay over the next 3 months,
// month by month, each saying how it's known (a listed ex-date, the holding's past dividends, or
// what it paid you a year ago).
import { useMemo } from "react";
import { api } from "../lib/api";
import type { DividendCalendarEvent } from "../lib/api";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import * as fmt from "../lib/format";
import { basisLabel, coverageText } from "../lib/dividendCalendar";
import "./DividendCalendarCard.css";

function groupByMonth(events: DividendCalendarEvent[]): Map<string, DividendCalendarEvent[]> {
  const out = new Map<string, DividendCalendarEvent[]>();
  for (const event of events) {
    const key = event.date.slice(0, 7);
    out.set(key, [...(out.get(key) ?? []), event]);
  }
  return out;
}

export default function DividendCalendarCard({ baseCurrency }: { baseCurrency: string }) {
  const res = useApiResource(resourceKey("dividendCalendar", baseCurrency), () => api.dividendCalendar(baseCurrency, 3));
  const cal = res.data ?? null;
  const byMonth = useMemo(() => groupByMonth(cal?.events ?? []), [cal?.events]);
  const currency = cal?.base_currency || baseCurrency;

  return (
    <section aria-labelledby="dividend-calendar-heading">
      <div className="coSectionHeader">
        <div>
          <p className="coEyebrow">AHEAD</p>
          <h2 className="coSectionTitle" id="dividend-calendar-heading">Dividends, next 3 months</h2>
        </div>
        {cal ? <div className="muted stockHoldingsMeta">Expected {fmt.formatMoney(cal.total_base, currency)} gross</div> : null}
      </div>
      <div className="card divCalCard">
        {res.error ? (
          <div className="muted" role="alert">Couldn't load the dividend calendar: {res.error.message}</div>
        ) : cal == null ? (
          <div className="muted" role="status">Loading…</div>
        ) : (
          <>
            <div className="divCalMonths" role="list" aria-label="Expected dividends by month">
              {cal.months.map((m) => (
                <div className="divCalMonth" role="listitem" key={m.month}>
                  <span className="divCalMonthName">{fmt.formatMonth(m.month, "medium")}</span>
                  <span className="divCalMonthValue">{fmt.formatMoney(m.amount_base, currency)}</span>
                  <span className="muted divCalMonthCount">
                    {m.count} payment{m.count === 1 ? "" : "s"}
                  </span>
                </div>
              ))}
            </div>
            {cal.events.length === 0 ? (
              <p className="muted divCalEmpty">
                No dividends expected in {fmt.formatDate(cal.from_date)} – {fmt.formatDate(cal.to_date)}.
              </p>
            ) : (
              <div className="listRows">
                {[...byMonth.entries()].map(([month, events]) => (
                  <div key={month} className="divCalGroup">
                    <p className="divCalGroupTitle">{fmt.formatMonth(month)}</p>
                    {events.map((event) => {
                      const basis = basisLabel(event.basis);
                      return (
                        <div className="listRow" key={`${event.asset_id}-${event.date}-${event.basis}`}>
                          <div className="listRowMain">
                            <span className="listRowTitle">
                              {event.company}
                              <span className="tag" title={basis.title}>{basis.label}</span>
                            </span>
                            <span className="listRowMeta">
                              <span>{event.symbol}</span>
                              <span>
                                {event.pay_date ? `Paid ${fmt.formatDate(event.pay_date)}` : event.ex_date ? `Ex-date ${fmt.formatDate(event.ex_date)}` : `Around ${fmt.formatDate(event.date)}`}
                              </span>
                              {event.amount_per_share != null ? (
                                <span>
                                  {fmt.formatNumber(event.shares, 4)} × {fmt.formatMoney(event.amount_per_share, event.currency)}
                                </span>
                              ) : null}
                            </span>
                          </div>
                          <div className="listRowValue good">
                            {event.amount_base != null ? fmt.formatMoney(event.amount_base, currency) : "—"}
                            {event.currency !== currency ? (
                              <span className="listRowValueSecondary muted">{fmt.formatMoney(event.amount, event.currency)}</span>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
            <p className="muted divCalNote">
              {coverageText(cal)}. Amounts are gross (before withholding tax) on the shares you hold today
              {cal.data_as_of ? `; market data from ${fmt.formatDate(cal.data_as_of)}` : ""}.
            </p>
          </>
        )}
      </div>
    </section>
  );
}
