// The one `api` object every page uses, assembled from the per-area clients (#368).
import { systemClient } from "./clients/system";
import { authClient } from "./clients/auth";
import { accountsClient } from "./clients/accounts";
import { wealthClient } from "./clients/wealth";
import { cashFlowClient } from "./clients/cashFlow";
import { cardsClient } from "./clients/cards";
import { ingestClient } from "./clients/ingest";
import { cryptoClient } from "./clients/crypto";
import { marketDataClient } from "./clients/marketData";
import { dataHubClient } from "./clients/dataHub";
import { incomeClient } from "./clients/income";

export const api = {
  ...systemClient,
  ...authClient,
  ...accountsClient,
  ...wealthClient,
  ...cashFlowClient,
  ...cardsClient,
  ...ingestClient,
  ...cryptoClient,
  ...marketDataClient,
  ...dataHubClient,
  ...incomeClient,
};
