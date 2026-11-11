// Health and live-update messages: API calls (split out of lib/api.ts, #368).
import { req } from "../http";
import type { Health } from "../types/system";

export const systemClient = {
  health: () => req<Health>("/health"),
};
