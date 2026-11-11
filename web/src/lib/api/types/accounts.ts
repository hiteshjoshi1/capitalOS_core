// Accounts, platforms and currencies: response and request types (split out of lib/api.ts, #368).

export type Platform = {
  id: number;
  code: string;
  name: string;
  platform_type: string; // BANK | BROKER | EXCHANGE | CARD_ISSUER | WALLET_PROVIDER
  country: string;       // SG | US | IN | HK | GLOBAL
  website?: string | null;
};

export type Account = {
  id: number;
  name: string;
  platform: string;      // legacy text column (DBS, IBKR, etc.)
  platform_id?: number | null;
  account_type: string;  // BANK | BROKER | EXCHANGE | WALLET | CREDIT_CARD | LOAN | MUTUAL_FUND
  currency: string;
  country?: string | null;
  /** #207: closed on this date (YYYY-MM-DD); counts up to it, nothing after. */
  closed_on?: string | null;
  /** #207: the month (YYYY-MM) the two fields below describe (default: latest completed). */
  data_month?: string | null;
  /** #207: date of the newest fact that month's valuation reads for the account. */
  last_data_as_of?: string | null;
  /** #207: set when that fact predates the month: its value is carried forward from this date. */
  carried_forward_from?: string | null;
};

/** PATCH /accounts/{id} (#207): a close date, or null to reopen. */
export type AccountUpdate = {
  closed_on: string | null;
};

export type Currency = {
  id: number;
  code: string;
  name?: string | null;
  country?: string | null;
};

export type AccountOptions = {
  account_types: string[];
  currencies: string[];
  countries: string[];
  currency_pattern: string;
};

export type AccountCreate = {
  name: string;
  platform_id: number | null;
  platform: string;
  account_type: string;
  currency: string;
  country: string | null;
};

export type PlatformCreate = {
  code: string;
  name: string;
  platform_type: string;
  country: string;
  website?: string | null;
};

export type PlatformOptions = {
  platform_types: string[];
  countries: string[];
  country_pattern: string;
};

export type CurrencyCreate = {
  code: string;
  name?: string | null;
  country?: string | null;
};
