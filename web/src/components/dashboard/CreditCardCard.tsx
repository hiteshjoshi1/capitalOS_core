import { Link } from "react-router-dom";
import type { CreditCardSummary } from "../../lib/api";

type CreditCardCardProps = {
  month: string;
  summary: CreditCardSummary | null;
  formatMoney: (value?: number, maximumFractionDigits?: number) => string;
};

export default function CreditCardCard({ month, summary, formatMoney }: CreditCardCardProps) {
  const cards = summary?.cards ?? [];
  const topCards = [...cards].sort((a, b) => b.current_due - a.current_due).slice(0, 2);

  return (
    <div className="card">
      <h2>Expenses &mdash; Credit Cards</h2>
      <div className="big small">{formatMoney(summary?.total_spend)}</div>
      <div className="muted">
        {cards.length > 0
          ? `Money out across ${cards.length} card${cards.length > 1 ? "s" : ""} in ${month}.`
          : "No credit card transactions for this month."}
      </div>

      {topCards.length > 0 ? (
        <div className="mini" style={{ marginTop: 10 }}>
          <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
            Highest spend cards
          </div>
          {topCards.map((card) => (
            <div
              key={card.account_id}
              style={{ display: "flex", justifyContent: "space-between", gap: 12, marginTop: 6 }}
            >
              <span>{card.card_name}</span>
              <span>{formatMoney(card.current_due)}</span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="hint" style={{ marginTop: 10 }}>
        Configured cards: {cards.length}
      </div>
      <Link className="exposureCardCta" to="/credit-cards" aria-label="Credit cards details">
        View details -&gt;
      </Link>
    </div>
  );
}
