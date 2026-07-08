type MonthControlProps = {
  month: string;
  onMonthChange: (month: string) => void;
};

function formatMonthLabel(month: string): string {
  const [yearStr, monStr] = month.split("-");
  const year = Number(yearStr);
  const mon = Number(monStr);
  if (!Number.isFinite(year) || !Number.isFinite(mon)) return month;
  return new Date(year, mon - 1, 1).toLocaleString("en", {
    month: "long",
    year: "numeric",
  });
}

export default function MonthControl({ month, onMonthChange }: MonthControlProps) {
  return (
    <label className="coPillBtn" title="Change month">
      <span aria-hidden="true">{formatMonthLabel(month)}</span>
      <input
        className="coPillBtnInput"
        aria-label="Month"
        type="month"
        value={month}
        onChange={(event) => onMonthChange(event.target.value)}
      />
    </label>
  );
}
