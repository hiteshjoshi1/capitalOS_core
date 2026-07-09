export type StatusPillTone = "good" | "warn" | "bad" | "neutral";

type StatusPillProps = {
  label: string;
  tone: StatusPillTone;
};

export default function StatusPill({ label, tone }: StatusPillProps) {
  return <span className={`statusPill statusPill--${tone}`}>{label}</span>;
}
