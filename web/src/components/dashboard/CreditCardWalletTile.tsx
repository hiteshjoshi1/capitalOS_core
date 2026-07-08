import DueStatusPill from "../DueStatusPill";
import type { DueStatus } from "../../lib/dueStatus";

/** Purely decorative, deterministic per-card gradients — not brand marks. */
const WALLET_GRADIENTS = [
  "linear-gradient(135deg, #1f3350 0%, #3c5a8a 100%)",
  "linear-gradient(135deg, #3a2414 0%, #7a4a1f 100%)",
  "linear-gradient(135deg, #2a2a2a 0%, #5c5c5c 100%)",
  "linear-gradient(135deg, #1f3d33 0%, #2f6d57 100%)",
  "linear-gradient(135deg, #3a1f3d 0%, #6d3f7a 100%)",
  "linear-gradient(135deg, #3d2a1f 0%, #8a5a3c 100%)",
];

function walletGradientForIndex(index: number): string {
  return WALLET_GRADIENTS[index % WALLET_GRADIENTS.length];
}

function utilizationColor(pct: number): string {
  if (pct >= 70) return "var(--bad)";
  if (pct >= 40) return "var(--warn)";
  return "var(--accent)";
}

type CreditCardWalletTileProps = {
  variant: "wallet" | "compact";
  name: string;
  meta: string;
  balanceLabel: string;
  limitLabel: string;
  utilPercent: number;
  dueStatus: DueStatus;
  dueDateLabel?: string | null;
  gradientIndex?: number;
};

export default function CreditCardWalletTile({
  variant,
  name,
  meta,
  balanceLabel,
  limitLabel,
  utilPercent,
  dueStatus,
  dueDateLabel,
  gradientIndex = 0,
}: CreditCardWalletTileProps) {
  const pct = Math.max(0, Math.min(100, utilPercent));

  if (variant === "wallet") {
    return (
      <div className="ccWalletTile" style={{ background: walletGradientForIndex(gradientIndex) }}>
        <div className="ccWalletTileHeader">
          <div>
            <strong className="ccWalletTileName">{name}</strong>
            <div className="ccWalletTileMeta">{meta}</div>
          </div>
          <span className="ccWalletTileBadge">{dueStatus.label}</span>
        </div>
        <div>
          <strong className="ccWalletTileBalance">{balanceLabel}</strong>
          <div className="ccWalletTileBar">
            <span style={{ width: `${pct}%` }} />
          </div>
          <span className="ccWalletTileSub">
            {pct}% of {limitLabel} limit
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="card liabCardTile">
      <div className="liabCardTileHeader">
        <div>
          <strong>{name}</strong>
          <div className="muted" style={{ fontSize: 12 }}>
            {meta}
          </div>
        </div>
        <strong style={{ fontSize: 16, whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
          {balanceLabel}
        </strong>
      </div>
      <div className="bar">
        <span style={{ width: `${pct}%`, background: utilizationColor(pct) }} />
      </div>
      <div className="liabCardTileFooter">
        <span className="muted" style={{ fontSize: 12 }}>
          {pct}% of {limitLabel} limit
        </span>
        <DueStatusPill status={dueStatus} dateLabel={dueDateLabel} />
      </div>
    </div>
  );
}
