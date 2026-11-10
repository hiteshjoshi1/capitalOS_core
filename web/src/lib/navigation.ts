export type NavItem = {
  label: string;
  to: string;
  exact?: boolean;
  matchPaths?: string[];
  hidden?: boolean;
};

export type AppSection = {
  id: "wealth" | "cashflow" | "liabilities" | "operations";
  label: string;
  icon: string;
  to: string;
  tabs: NavItem[];
  matchPaths?: string[];
};

export type UtilityNavItem = NavItem & {
  badgeKey?: "alerts";
};

export const APP_SECTIONS: AppSection[] = [
  {
    id: "wealth",
    label: "Wealth",
    icon: "account_balance",
    to: "/wealth",
    tabs: [
      { label: "Overview", to: "/wealth", exact: true },
      { label: "Stocks", to: "/holdings" },
      { label: "Crypto", to: "/crypto/holdings" },
      { label: "Cash", to: "/cash" },
      // #267: Dividends became Income (dividends + interest); /dividends redirects here.
      { label: "Income", to: "/income", matchPaths: ["/dividends"] },
      { label: "Risk", to: "/risk" },
      { label: "History", to: "/wealth/history" },
    ],
  },
  {
    id: "cashflow",
    label: "Cash Flow",
    icon: "account_balance_wallet",
    to: "/cash-flow",
    matchPaths: ["/wealth/cash-flow"],
    tabs: [
      { label: "Overview", to: "/cash-flow", exact: true, matchPaths: ["/cash-flow", "/wealth/cash-flow"] },
      { label: "Income", to: "/cash-flow/income" },
      { label: "Expenses", to: "/cash-flow/expenses" },
      { label: "Map Transactions", to: "/cash-flow/map-transactions", matchPaths: ["/cash-flow/map-transactions", "/cash-flow/mapping"] },
    ],
  },
  {
    id: "liabilities",
    label: "Liabilities",
    icon: "trending_down",
    to: "/liabilities",
    tabs: [],
  },
  {
    id: "operations",
    label: "Data Hub",
    icon: "settings_applications",
    to: "/operations",
    tabs: [
      // #321 (#309): three tabs. What needs you, every source with its action, and uploads.
      // Adding an account or wallet and Market data open from Accounts & sources ("+ Add",
      // each row's action), so they count as that tab; the platform directory and token
      // allowlist moved to Settings → Admin.
      { label: "Inbox", to: "/operations", exact: true },
      {
        label: "Accounts & sources",
        to: "/operations/sources",
        matchPaths: ["/operations/sources", "/add", "/market-data"],
      },
      { label: "Imports", to: "/ingest" },
    ],
  },
];

// #317: Alerts moved to the header bell (the Data Hub inbox); /alerts still works.
export const UTILITY_NAV_ITEMS: UtilityNavItem[] = [];

function itemMatchScore(item: NavItem, pathname: string): number {
  const candidates = item.matchPaths ?? [item.to];
  let score = -1;

  for (const candidate of candidates) {
    const matched = item.exact
      ? pathname === candidate
      : pathname === candidate || pathname.startsWith(`${candidate}/`);
    if (matched) {
      score = Math.max(score, candidate.length);
    }
  }

  return score;
}

export function isNavItemActive(item: NavItem, pathname: string): boolean {
  return itemMatchScore(item, pathname) >= 0;
}

export function findActiveSection(pathname: string): AppSection | null {
  let activeSection: AppSection | null = null;
  let activeScore = -1;

  for (const section of APP_SECTIONS) {
    const sectionCandidates: NavItem[] = [
      { label: section.label, to: section.to, exact: true, matchPaths: section.matchPaths },
      ...section.tabs,
    ];
    const score = Math.max(...sectionCandidates.map((item) => itemMatchScore(item, pathname)));
    if (score > activeScore) {
      activeSection = section;
      activeScore = score;
    }
  }

  return activeScore >= 0 ? activeSection : null;
}

export function findActiveTab(section: AppSection, pathname: string): NavItem | null {
  let activeTab: NavItem | null = null;
  let activeScore = -1;

  for (const tab of section.tabs) {
    const score = itemMatchScore(tab, pathname);
    if (score > activeScore) {
      activeTab = tab;
      activeScore = score;
    }
  }

  return activeScore >= 0 ? activeTab : null;
}
