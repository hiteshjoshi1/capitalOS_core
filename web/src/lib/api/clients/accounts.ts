// Accounts, platforms and currencies: API calls (split out of lib/api.ts, #368).
import { req } from "../http";
import type { Account, AccountCreate, AccountOptions, AccountUpdate, Currency, CurrencyCreate, Platform, PlatformCreate, PlatformOptions } from "../types/accounts";

export const accountsClient = {
  platforms: () => req<Platform[]>("/platforms"),
  platformOptions: () => req<PlatformOptions>("/platforms/options"),
  createPlatform: (payload: PlatformCreate) =>
    req<Platform>("/platforms", { method: "POST", body: JSON.stringify(payload) }),
  accounts: () => req<Account[]>("/accounts"),
  accountOptions: () => req<AccountOptions>("/accounts/options"),
  createAccount: (payload: AccountCreate) =>
    req<Account>("/accounts", { method: "POST", body: JSON.stringify(payload) }),
  updateAccount: (id: number, patch: AccountUpdate) =>
    req<Account>(`/accounts/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  currencies: () => req<Currency[]>("/currencies"),
  createCurrency: (payload: CurrencyCreate) =>
    req<Currency>("/currencies", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
