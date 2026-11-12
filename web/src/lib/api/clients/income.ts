// Income and dividends: API calls (split out of lib/api.ts, #368).
import { req } from "../http";
import type { DividendCalendar, DividendHistory, DividendsByCompany, DividendsSummary, ExpectedDividendsOverview, IncomeSummary } from "../types/income";

export const incomeClient = {
  // #417 (U17): dividends expected over the next `months` months.
  dividendCalendar: (baseCurrency = "SGD", months = 3) =>
    req<DividendCalendar>(
      `/dividends/calendar?base_currency=${encodeURIComponent(baseCurrency)}&months=${encodeURIComponent(String(months))}`,
    ),
  incomeSummary: (month: string, baseCurrency = "SGD") =>
    req<IncomeSummary>(
      `/income/summary?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`,
    ),
  dividendsSummary: (
    fromMonth: string,
    toMonth: string,
    period: "month" | "quarter" | "year",
    baseCurrency = "SGD",
    assumedTaxRate = 0,
    countryTaxRates?: string,
  ) =>
    req<DividendsSummary>(
      `/dividends/summary?from_month=${encodeURIComponent(fromMonth)}&to_month=${encodeURIComponent(toMonth)}&period=${encodeURIComponent(period)}&base_currency=${encodeURIComponent(baseCurrency)}&assumed_tax_rate=${encodeURIComponent(String(assumedTaxRate))}${countryTaxRates ? `&country_tax_rates=${encodeURIComponent(countryTaxRates)}` : ""}`
    ),
  dividendsByCompany: (
    fromMonth: string,
    toMonth: string,
    baseCurrency = "SGD",
    assumedTaxRate = 0,
    countryTaxRates?: string,
  ) =>
    req<DividendsByCompany>(
      `/dividends/by-company?from_month=${encodeURIComponent(fromMonth)}&to_month=${encodeURIComponent(toMonth)}&base_currency=${encodeURIComponent(baseCurrency)}&assumed_tax_rate=${encodeURIComponent(String(assumedTaxRate))}${countryTaxRates ? `&country_tax_rates=${encodeURIComponent(countryTaxRates)}` : ""}`
    ),
  dividendsHistory: (
    assetId: number,
    fromMonth: string,
    toMonth: string,
    baseCurrency = "SGD",
    assumedTaxRate = 0,
    countryTaxRates?: string,
  ) =>
    req<DividendHistory>(
      `/dividends/history?asset_id=${encodeURIComponent(String(assetId))}&from_month=${encodeURIComponent(fromMonth)}&to_month=${encodeURIComponent(toMonth)}&base_currency=${encodeURIComponent(baseCurrency)}&assumed_tax_rate=${encodeURIComponent(String(assumedTaxRate))}${countryTaxRates ? `&country_tax_rates=${encodeURIComponent(countryTaxRates)}` : ""}`
    ),
  expectedDividendsOverview: (
    fromMonth: string,
    toMonth: string,
    baseCurrency = "SGD",
    assumedTaxRate = 0,
    countryTaxRates?: string,
  ) =>
    req<ExpectedDividendsOverview>(
      `/dividends/expected/overview?from_month=${encodeURIComponent(fromMonth)}&to_month=${encodeURIComponent(toMonth)}&base_currency=${encodeURIComponent(baseCurrency)}&assumed_tax_rate=${encodeURIComponent(String(assumedTaxRate))}${countryTaxRates ? `&country_tax_rates=${encodeURIComponent(countryTaxRates)}` : ""}`
    ),
};
