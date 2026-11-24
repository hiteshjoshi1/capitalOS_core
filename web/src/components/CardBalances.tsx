import { useId, useState, type FormEvent } from "react";

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
 * Statement balances are typed in on one "Update balances" sheet for all cards (#472).
 */
export default function CardBalances({ baseCurrency }: { baseCurrency: string }) {
  const balances = useApiResource(resourceKey("creditCardBalances", baseCurrency), () =>
    api.creditCardBalances(baseCurrency),
  );
  const data = balances.data;
  const [updating, setUpdating] = useState(false);
  const sheetId = useId();

  return (
    <section aria-labelledby="card-balances-title">
      <div className="cashFlowSectionHeading cardBalancesHeading">
        <div>
          <p className="wealthEyebrow">Owed and paid</p>
          <h2 className="cashFlowSectionTitle" id="card-balances-title">
            Card balances
          </h2>
        </div>
        {data && data.cards.length > 0 ? (
          <button
            type="button"
            className={`btn${updating ? "" : " btnPrimary"}`}
            aria-expanded={updating}
            aria-controls={updating ? sheetId : undefined}
            onClick={() => setUpdating((open) => !open)}
          >
            Update balances
          </button>
        ) : null}
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
          {updating ? (
            <UpdateBalancesSheet
              id={sheetId}
              cards={data.cards}
              baseCurrency={baseCurrency}
              onSaved={() => void balances.reload()}
              onClose={() => setUpdating(false)}
            />
          ) : null}
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
        <p className="muted cardBalanceFacts">
          No statement balance on file: this month&apos;s charges only, an estimate. Add one under Update balances.
        </p>
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

type BalanceDraft = { asOf: string; owed: string; dueDate: string; minimum: string };

const EMPTY_DRAFT: BalanceDraft = { asOf: "", owed: "", dueDate: "", minimum: "" };

type BalanceEntry = {
  card: CreditCardBalanceItem;
  payload: { as_of_date: string; owed: number; due_date: string | null; minimum_due: number | null };
};

/** A card's typed-in statement, or an error saying what's missing. Null when left empty (skipped). */
function parseDraft(card: CreditCardBalanceItem, draft: BalanceDraft): BalanceEntry | string | null {
  if (!draft.asOf && !draft.owed.trim() && !draft.dueDate && !draft.minimum.trim()) return null;
  const owed = Number(draft.owed.replace(/,/g, ""));
  if (!draft.asOf || draft.owed.trim() === "" || !Number.isFinite(owed)) {
    return "Enter the statement date and the amount it says you owe.";
  }
  const min = draft.dueDate && draft.minimum.trim() !== "" ? Number(draft.minimum.replace(/,/g, "")) : null;
  if (min != null && !Number.isFinite(min)) {
    return "The minimum payment should be a number, or leave it empty.";
  }
  return {
    card,
    payload: { as_of_date: draft.asOf, owed, due_date: draft.dueDate || null, minimum_due: min },
  };
}

/**
 * One "Update balances" sheet for every card (#472, V19 of #432), in place of a form under each
 * card: type in each card's newest statement (date, amount owed, optional due date). A card left
 * empty is skipped. Each filled card is saved with the same call as before (#300).
 */
function UpdateBalancesSheet({
  id,
  cards,
  baseCurrency,
  onSaved,
  onClose,
}: {
  id: string;
  cards: CreditCardBalanceItem[];
  baseCurrency: string;
  onSaved: () => void;
  onClose: () => void;
}) {
  const [drafts, setDrafts] = useState<Record<number, BalanceDraft>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const draftFor = (accountId: number) => drafts[accountId] ?? EMPTY_DRAFT;
  const setField = (accountId: number, field: keyof BalanceDraft, value: string) =>
    setDrafts((prev) => ({ ...prev, [accountId]: { ...(prev[accountId] ?? EMPTY_DRAFT), [field]: value } }));

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const entries: BalanceEntry[] = [];
    const found: Record<number, string> = {};
    for (const card of cards) {
      const parsed = parseDraft(card, draftFor(card.account_id));
      if (typeof parsed === "string") found[card.account_id] = parsed;
      else if (parsed) entries.push(parsed);
    }
    setErrors(found);
    if (Object.keys(found).length > 0) {
      setFormError(null);
      return;
    }
    if (entries.length === 0) {
      setFormError("Fill in at least one card's statement date and amount owed.");
      return;
    }
    setFormError(null);
    setSaving(true);
    const failed: Record<number, string> = {};
    const saved: number[] = [];
    // One card at a time: each save recomputes the balances (and History) from its date.
    for (const entry of entries) {
      try {
        await api.setCreditCardBalance(entry.card.account_id, entry.payload, baseCurrency);
        saved.push(entry.card.account_id);
      } catch (err) {
        failed[entry.card.account_id] = err instanceof Error ? err.message : "Couldn't save the balance.";
      }
    }
    setSaving(false);
    setErrors(failed);
    setDrafts((prev) => {
      const next = { ...prev };
      for (const accountId of saved) delete next[accountId];
      return next;
    });
    if (saved.length > 0) onSaved();
    if (Object.keys(failed).length === 0) onClose();
  };

  return (
    <form id={id} className="card cardBalanceSheet" aria-label="Update balances" onSubmit={(event) => void onSubmit(event)}>
      <p className="muted cardBalanceSheetIntro">
        From each card&apos;s newest statement: its date and the amount it says you owe. Leave a card empty to keep it as
        it is.
      </p>
      {cards.map((card) => {
        const draft = draftFor(card.account_id);
        const error = errors[card.account_id];
        return (
          <fieldset className="cardBalanceSheetCard" key={card.account_id}>
            <legend>{card.card_name}</legend>
            <p className="muted cardBalanceSheetHint">
              {card.method === "running" && card.last_balance_date
                ? `Statement of ${fmt.formatDate(card.last_balance_date)}: ${money(card.last_balance, card.currency)}`
                : "No statement balance on file"}
            </p>
            <div className="cardBalanceSheetFields">
              <label>
                <span>Statement date</span>
                <input type="date" value={draft.asOf} onChange={(e) => setField(card.account_id, "asOf", e.target.value)} />
              </label>
              <label>
                <span>Amount owed ({card.currency})</span>
                <input
                  inputMode="decimal"
                  value={draft.owed}
                  onChange={(e) => setField(card.account_id, "owed", e.target.value)}
                  placeholder="0.00"
                />
              </label>
              <label>
                <span>Payment due date (optional)</span>
                <input type="date" value={draft.dueDate} onChange={(e) => setField(card.account_id, "dueDate", e.target.value)} />
              </label>
              {draft.dueDate ? (
                <label>
                  <span>Minimum payment ({card.currency}, optional)</span>
                  <input
                    inputMode="decimal"
                    value={draft.minimum}
                    onChange={(e) => setField(card.account_id, "minimum", e.target.value)}
                    placeholder="0.00"
                  />
                </label>
              ) : null}
            </div>
            {error ? (
              <p className="cardBalanceWarn" role="alert">
                {error}
              </p>
            ) : null}
          </fieldset>
        );
      })}
      {formError ? (
        <p className="cardBalanceWarn" role="alert">
          {formError}
        </p>
      ) : null}
      <div className="cardBalanceFormActions">
        <button type="submit" className="btn btnPrimary" disabled={saving}>
          {saving ? "Saving…" : "Save balances"}
        </button>
        <button type="button" className="btn" onClick={onClose} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  );
}
