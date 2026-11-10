import { useState, type FormEvent } from "react";

import { api, type CreditCardBalanceItem } from "../lib/api";
import { differenceReason, money, owedLabel } from "../lib/cardBalances";
import * as fmt from "../lib/format";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import LoadError from "./LoadError";
import "./CardBalances.css";

/**
 * What each card owes, what was paid, and whether each statement adds up (#300, D-76).
 * The owed amount is the card's newest dated balance (a statement) carried by its
 * transactions since; each statement is checked against the transactions before it.
 */
export default function CardBalances({ baseCurrency }: { baseCurrency: string }) {
  const balances = useApiResource(resourceKey("creditCardBalances", baseCurrency), () =>
    api.creditCardBalances(baseCurrency),
  );
  const data = balances.data;

  return (
    <section aria-labelledby="card-balances-title">
      <div className="cashFlowSectionHeading">
        <p className="wealthEyebrow">Owed and paid</p>
        <h2 className="cashFlowSectionTitle" id="card-balances-title">
          Card balances
        </h2>
      </div>
      {balances.error && !data ? (
        <LoadError title="Couldn't load card balances" error={balances.error} onRetry={() => void balances.reload()} />
      ) : null}
      {!data && !balances.error ? (
        <div className="card" role="status">
          Loading…
        </div>
      ) : null}
      {data ? (
        <div className="cardBalancesList">
          {data.flagged_count > 0 ? (
            <p className="cardBalancesAlert" role="status">
              {data.flagged_count === 1
                ? "1 statement doesn't add up to its transactions. See below."
                : `${data.flagged_count} statements don't add up to their transactions. See below.`}
            </p>
          ) : null}
          {data.cards.map((card) => (
            <CardBalanceRow key={card.account_id} card={card} onSaved={() => void balances.reload()} baseCurrency={baseCurrency} />
          ))}
          {data.cards.length === 0 ? <p className="muted">No cards.</p> : null}
        </div>
      ) : null}
    </section>
  );
}

function CardBalanceRow({
  card,
  onSaved,
  baseCurrency,
}: {
  card: CreditCardBalanceItem;
  onSaved: () => void;
  baseCurrency: string;
}) {
  const closed = card.periods.filter((p) => p.to_date != null);
  return (
    <article className="card cardBalanceCard">
      <header className="cardBalanceHead">
        <div className="cardBalanceName">
          <strong>{card.card_name}</strong>
          <span className="muted">{card.issuer}</span>
        </div>
        <div className={`cardBalanceOwed${card.owed_now < -0.005 ? " cardBalanceCredit" : ""}`}>{owedLabel(card)}</div>
      </header>

      {card.method === "running" && card.last_balance_date ? (
        <ul className="cardBalanceFacts">
          <li>
            Statement of {fmt.formatDate(card.last_balance_date)}: {money(card.last_balance, card.currency)}
          </li>
          <li>
            Since then: {money(card.charges_since, card.currency)} charged, {money(card.paid_since, card.currency)} paid
          </li>
          {card.paid_in_full != null ? (
            <li className={card.paid_in_full ? "cardBalanceGood" : "cardBalanceWarn"}>
              {card.paid_in_full
                ? "That statement is paid in full"
                : `${money(Math.max((card.last_balance ?? 0) - card.paid_since, 0), card.currency)} of it still to pay${
                    // A printed/typed-in due has its own line below (#352).
                    card.due_date && card.due_source === "configured" ? `, due ${fmt.formatDate(card.due_date)}` : ""
                  }`}
            </li>
          ) : null}
          {card.last_transaction_date ? (
            <li className="muted">Transactions up to {fmt.formatDate(card.last_transaction_date)}</li>
          ) : null}
          <DueLine card={card} onSaved={onSaved} baseCurrency={baseCurrency} />
        </ul>
      ) : (
        <div className="cardBalanceFacts">
          <p className="muted">
            No statement balance on file, so this is this month's charges only (an estimate). Enter the balance from
            your last statement to carry it properly.
          </p>
          <StatementBalanceForm accountId={card.account_id} currency={card.currency} onSaved={onSaved} baseCurrency={baseCurrency} />
        </div>
      )}

      <p className="cardBalanceFees">
        Fees and interest this year: <strong>{money(card.fees_interest_ytd, card.currency)}</strong>
      </p>

      {closed.length > 0 ? (
        <details className="cardBalanceChecks" open={card.flagged_count > 0}>
          <summary>
            Statement checks: {closed.length - card.flagged_count} of {closed.length} add up
            {card.flagged_count > 0 ? ` · ${card.flagged_count} to look at` : ""}
          </summary>
          <ol className="cardBalancePeriods">
            {closed.map((period) => (
              <li key={period.from_date} className={period.flagged ? "cardBalancePeriodFlagged" : undefined}>
                <div className="cardBalancePeriodDates">
                  {fmt.formatDate(period.from_date)} → {fmt.formatDate(period.to_date)}
                  <span aria-hidden="true">{period.flagged ? " ⚠" : " ✓"}</span>
                  <span className="srOnly">{period.flagged ? "doesn't add up" : "adds up"}</span>
                </div>
                <div className="cardBalancePeriodMath">
                  {money(period.opening, card.currency)} + {money(period.charges + period.fees + period.interest, card.currency)}{" "}
                  charged − {money(period.payments + period.credits, card.currency)} paid ={" "}
                  {money(period.expected, card.currency)}; statement {money(period.printed, card.currency)}
                </div>
                {period.fees + period.interest > 0.005 ? (
                  <div className="cardBalanceWarn">
                    Includes {money(period.fees, card.currency)} fees and {money(period.interest, card.currency)} interest
                  </div>
                ) : null}
                {period.flagged ? <div className="cardBalanceWarn">{differenceReason(period, card.currency)}</div> : null}
                {(period.bank_payments ?? 0) > 0.005 ? (
                  <div className="cardBalanceNote">
                    Includes {money(period.bank_payments ?? 0, card.currency)} paid from your bank account that the card
                    file doesn&apos;t list.
                  </div>
                ) : null}
                {!period.flagged && period.note ? <div className="cardBalanceNote">{period.note}</div> : null}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </article>
  );
}

/** The newest statement's payment due (#352, D-94): printed or typed in, never guessed. */
function DueLine({
  card,
  onSaved,
  baseCurrency,
}: {
  card: CreditCardBalanceItem;
  onSaved: () => void;
  baseCurrency: string;
}) {
  const [editing, setEditing] = useState(false);
  const known = card.due_source === "statement" || card.due_source === "manual";
  if (editing) {
    return (
      <li>
        <DueForm
          card={card}
          baseCurrency={baseCurrency}
          onSaved={() => {
            setEditing(false);
            onSaved();
          }}
          onCancel={() => setEditing(false)}
        />
      </li>
    );
  }
  if (!known || !card.due_date) {
    return (
      <li className="cardBalanceDue">
        <span className="muted">Payment due date unknown: your card files don&apos;t state it.</span>{" "}
        <button type="button" className="btn btnSmall" onClick={() => setEditing(true)}>
          Add due date
        </button>
      </li>
    );
  }
  const due = fmt.formatDate(card.due_date);
  const statement = card.due_statement_date ? ` (statement of ${fmt.formatDate(card.due_statement_date)})` : "";
  let text: string;
  let tone: string;
  if (card.due_status === "paid") {
    text = `Paid, due ${due}${statement}`;
    tone = "cardBalanceGood";
  } else {
    const left = card.remaining_due != null ? `${money(card.remaining_due, card.currency)} to pay` : "Payment";
    const when = card.due_status === "overdue" ? `overdue since ${due}` : `due ${due}`;
    const minimum =
      card.minimum_due != null
        ? card.minimum_paid
          ? "; minimum paid, interest runs on the rest"
          : `; minimum ${money(card.minimum_due, card.currency)}`
        : "";
    text = `${left}, ${when}${statement}${minimum}`;
    tone = card.due_status === "overdue" || card.due_status === "due_soon" ? "cardBalanceWarn" : "";
  }
  return (
    <li className={`cardBalanceDue ${tone}`.trim()}>
      {text}{" "}
      {card.due_source === "manual" ? (
        <button type="button" className="linkBtn" onClick={() => setEditing(true)}>
          Change
        </button>
      ) : null}
    </li>
  );
}

function DueForm({
  card,
  baseCurrency,
  onSaved,
  onCancel,
}: {
  card: CreditCardBalanceItem;
  baseCurrency: string;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [statementDate, setStatementDate] = useState(card.due_statement_date ?? card.last_balance_date ?? "");
  const [dueDate, setDueDate] = useState(card.due_source === "manual" ? card.due_date ?? "" : "");
  const [minimum, setMinimum] = useState(card.minimum_due != null ? String(card.minimum_due) : "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const min = minimum.trim() === "" ? null : Number(minimum.replace(/,/g, ""));
    if (!statementDate || !dueDate) {
      setError("Enter the statement date and the payment due date it prints.");
      return;
    }
    if (min != null && !Number.isFinite(min)) {
      setError("The minimum payment should be a number, or leave it empty.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.setCreditCardDue(
        card.account_id,
        { statement_date: statementDate, due_date: dueDate, minimum_due: min },
        baseCurrency,
      );
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the due date.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="cardBalanceForm" onSubmit={(event) => void onSubmit(event)} aria-label={`Payment due date for ${card.card_name}`}>
      <label>
        <span>Statement date</span>
        <input type="date" value={statementDate} onChange={(e) => setStatementDate(e.target.value)} required />
      </label>
      <label>
        <span>Payment due date</span>
        <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} required />
      </label>
      <label>
        <span>Minimum payment ({card.currency}, optional)</span>
        <input inputMode="decimal" value={minimum} onChange={(e) => setMinimum(e.target.value)} placeholder="0.00" />
      </label>
      <div className="cardBalanceFormActions">
        <button type="submit" className="btn" disabled={saving}>
          {saving ? "Saving…" : "Save due date"}
        </button>
        <button type="button" className="btn btnSmall" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {error ? (
        <p className="cardBalanceWarn" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

function StatementBalanceForm({
  accountId,
  currency,
  onSaved,
  baseCurrency,
}: {
  accountId: number;
  currency: string;
  onSaved: () => void;
  baseCurrency: string;
}) {
  const [asOf, setAsOf] = useState("");
  const [owed, setOwed] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [minimum, setMinimum] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const amount = Number(owed.replace(/,/g, ""));
    const min = minimum.trim() === "" ? null : Number(minimum.replace(/,/g, ""));
    if (!asOf || !Number.isFinite(amount)) {
      setError("Enter the statement date and the amount it says you owe.");
      return;
    }
    if (min != null && !Number.isFinite(min)) {
      setError("The minimum payment should be a number, or leave it empty.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.setCreditCardBalance(
        accountId,
        { as_of_date: asOf, owed: amount, due_date: dueDate || null, minimum_due: dueDate ? min : null },
        baseCurrency,
      );
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the balance.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="cardBalanceForm" onSubmit={(event) => void onSubmit(event)}>
      <label>
        <span>Statement date</span>
        <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} required />
      </label>
      <label>
        <span>Amount owed ({currency})</span>
        <input inputMode="decimal" value={owed} onChange={(e) => setOwed(e.target.value)} placeholder="0.00" required />
      </label>
      <label>
        <span>Payment due date (optional)</span>
        <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
      </label>
      {dueDate ? (
        <label>
          <span>Minimum payment ({currency}, optional)</span>
          <input inputMode="decimal" value={minimum} onChange={(e) => setMinimum(e.target.value)} placeholder="0.00" />
        </label>
      ) : null}
      <button type="submit" className="btn" disabled={saving}>
        {saving ? "Saving…" : "Save balance"}
      </button>
      {error ? (
        <p className="cardBalanceWarn" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
