type AllocationRow = {
  key: string;
  value: number;
  percent: number;
};

type AllocationCardProps = {
  title: string;
  firstColumnLabel: string;
  rows: AllocationRow[];
  emptyLabel: string;
  formatMoney: (value?: number, maximumFractionDigits?: number) => string;
};

export default function AllocationCard({
  title,
  firstColumnLabel,
  rows,
  emptyLabel,
  formatMoney,
}: AllocationCardProps) {
  return (
    <div className="card">
      <h2>{title}</h2>
      <div className="mini">
        <table className="table">
          <thead>
            <tr>
              <th>{firstColumnLabel}</th>
              <th className="right">Value</th>
              <th className="right">%</th>
            </tr>
          </thead>
          <tbody>
            {rows.length ? (
              rows.map((row) => (
                <tr key={row.key}>
                  <td>{row.key}</td>
                  <td className="right">{formatMoney(row.value)}</td>
                  <td className="right">{row.percent.toFixed(1)}%</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="muted" colSpan={3}>
                  {emptyLabel}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="hintTag">Snapshot</div>
    </div>
  );
}
