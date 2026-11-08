import type { InboxItem } from "./api";
import { sourceLink } from "./sourceFreshness";

/** One shared reading of the Data Hub inbox (#316) for the Inbox, the bell and Alerts (#317). */

export const INBOX_SEVERITY_LABEL: Record<InboxItem["severity"], string> = {
  high: "Urgent",
  medium: "Needs a look",
  low: "When you can",
};

/** The page an item's action opens, or null for an action that runs in place (a refresh).
 *  An overdue upload source opens Upload prefilled (account, as-of, what's due, #278). */
export function inboxItemRoute(item: InboxItem): string | null {
  if (item.source) {
    const link = sourceLink(item.source);
    if (link && link.startsWith("/ingest")) return link;
  }
  const action = item.action;
  if (!action?.route) return null;
  const query = new URLSearchParams(action.params ?? {}).toString();
  return query ? `${action.route}?${query}` : action.route;
}
