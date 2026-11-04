import { useBaseCurrency } from "../context/CurrencyContext";
import { CURRENCY_OPTIONS } from "../lib/format";

/** The header's base-currency pill (#150): one control, one option list, shared state. */
export default function BaseCurrencyPicker() {
  const [baseCurrency, setBaseCurrency] = useBaseCurrency();
  return (
    <label className="coPillBtn">
      <span aria-hidden="true">{baseCurrency}</span>
      <select
        className="coPillBtnInput"
        aria-label="Base currency"
        value={baseCurrency}
        onChange={(event) => setBaseCurrency(event.target.value)}
      >
        {CURRENCY_OPTIONS.map((code) => (
          <option key={code} value={code}>
            {code}
          </option>
        ))}
      </select>
    </label>
  );
}
