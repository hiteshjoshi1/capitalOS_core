import { describe, expect, it } from "vitest";

import {
  ADD_KINDS,
  availableKinds,
  defaultCurrency,
  deriveCode,
  detailsMissing,
  draftFromPlatform,
  joinMissing,
  kindMeta,
  parseKind,
  platformMissing,
  platformsForKind,
  whereMissing,
} from "../lib/addFlow";
import type { Platform } from "../lib/api";

const p = (id: number, name: string, platform_type: string, country = "SG"): Platform => ({
  id, code: name.toUpperCase(), name, platform_type, country, website: null,
});

describe("addFlow helpers (#319)", () => {
  it("offers only kinds the API can create, plus wallets", () => {
    expect(availableKinds(["BANK"]).map((k) => k.id)).toEqual(["bank", "wallet"]);
    expect(availableKinds(ADD_KINDS.flatMap((k) => (k.accountType ? [k.accountType] : []))).length).toBe(ADD_KINDS.length);
  });

  it("parses ?what=", () => {
    expect(parseKind("card")).toBe("card");
    expect(parseKind("nope")).toBeNull();
    expect(parseKind(null)).toBeNull();
  });

  it("filters platforms by the kind's types, sorted; all when asked or when none fit", () => {
    const all = [p(1, "Zeta", "BANK"), p(2, "Amex", "CARD_ISSUER"), p(3, "IBKR", "BROKER")];
    const card = kindMeta("card")!;
    expect(platformsForKind(all, card, false).map((x) => x.name)).toEqual(["Amex", "Zeta"]);
    expect(platformsForKind(all, card, true)).toHaveLength(3);
    expect(platformsForKind(all, kindMeta("exchange")!, false)).toHaveLength(3);
  });

  it("defaults from the platform", () => {
    expect(draftFromPlatform(p(1, "DBS", "BANK"), kindMeta("bank")!)).toEqual({
      name: "DBS Bank account", currency: "SGD", country: "SG",
    });
    expect(draftFromPlatform(p(2, "Binance", "EXCHANGE", "GLOBAL"), kindMeta("exchange")!)).toEqual({
      name: "Binance Crypto exchange", currency: "", country: "",
    });
    expect(defaultCurrency("in")).toBe("INR");
  });

  it("derives a valid platform code from the name", () => {
    expect(deriveCode("DBS Bank")).toBe("DBS_BANK");
    expect(deriveCode("  Crypto.com (SG) ")).toBe("CRYPTO_COM_SG");
    expect(deriveCode("")).toBe("");
  });

  it("names what each step still needs", () => {
    expect(whereMissing(kindMeta("bank")!, null, null)).toEqual(["pick where the account is (a platform)"]);
    expect(whereMissing(kindMeta("bank")!, 1, null)).toEqual([]);
    expect(whereMissing(kindMeta("wallet")!, null, null)).toEqual(["pick the wallet's chain"]);
    expect(detailsMissing({ name: "x", currency: "SGD", country: "" })).toEqual([]);
    expect(detailsMissing({ name: " ", currency: "SG", country: "SINGAPORE" })).toHaveLength(3);
    expect(platformMissing({ code: "A B", name: "", platform_type: "", country: "" })).toHaveLength(4);
    expect(joinMissing(["a", "b", "c"])).toBe("a, b and c");
    expect(joinMissing(["a"])).toBe("a");
  });
});
