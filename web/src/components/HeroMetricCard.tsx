import type { ReactNode } from "react";
import Delta from "./Delta";
import type { DeltaProps } from "./Delta";

type HeroDelta = {
  label: string;
  value: string;
  positive: boolean;
};

type HeroMetricCardProps = {
  eyebrow: string;
  value: string;
  /** The headline's change, shown as a chip next to it (#224: one <Delta> everywhere). */
  delta?: DeltaProps | null;
  insightText?: string | null;
  deltaRow?: HeroDelta[];
  children?: ReactNode;
};

export default function HeroMetricCard({
  eyebrow,
  value,
  delta,
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
        {delta ? <Delta show="pct" variant="chip" {...delta} /> : null}
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
