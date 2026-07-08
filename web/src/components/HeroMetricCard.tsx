import type { ReactNode } from "react";

type HeroDelta = {
  label: string;
  value: string;
  positive: boolean;
};

type HeroMetricCardProps = {
  eyebrow: string;
  value: string;
  deltaChip?: { text: string; positive: boolean } | null;
  insightText?: string | null;
  deltaRow?: HeroDelta[];
  children?: ReactNode;
};

export default function HeroMetricCard({
  eyebrow,
  value,
  deltaChip,
  insightText,
  deltaRow,
  children,
}: HeroMetricCardProps) {
  return (
    <article className="coHeroCard">
      <div className="coHeroCardHeader">
        <p className="coHeroEyebrow">{eyebrow}</p>
      </div>
      <div className="coHeroValueRow">
        <span className="coHeroValue">{value}</span>
        {deltaChip ? (
          <span className={`coChip${deltaChip.positive ? " coChipPositive" : " coChipNegative"}`}>
            {deltaChip.text}
          </span>
        ) : null}
      </div>
      {insightText ? <p className="coHeroFreshness">{insightText}</p> : null}
      {deltaRow && deltaRow.length > 0 ? (
        <div className="coHeroDeltaRow">
          {deltaRow.map((delta) => (
            <div className="coHeroDelta" key={delta.label}>
              <span className="coHeroDeltaLabel">{delta.label}</span>
              <strong className={delta.positive ? "wealthTrendPositive" : "wealthTrendNegative"}>
                {delta.value}
              </strong>
            </div>
          ))}
        </div>
      ) : null}
      {children}
    </article>
  );
}
