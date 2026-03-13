type MonthControlProps = {
  month: string;
  onMonthChange: (month: string) => void;
};

export default function MonthControl({ month, onMonthChange }: MonthControlProps) {
  return (
    <label className="pill monthControl">
      <span>Month</span>
      <input
        className="monthInput"
        aria-label="Month"
        type="month"
        value={month}
        onChange={(event) => onMonthChange(event.target.value)}
      />
    </label>
  );
}
