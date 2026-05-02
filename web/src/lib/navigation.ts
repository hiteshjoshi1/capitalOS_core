export type NavItem = {
  label: string;
  to: string;
  exact?: boolean;
  matchPaths?: string[];
  hidden?: boolean;
};

export type AppSection = {
  id: "wealth" | "liabilities" | "operations" | "intelligence";
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
      { label: "Dividends", to: "/dividends" },
      { label: "Crypto", to: "/crypto/holdings" },
      { label: "Cash", to: "/cash" },
      { label: "Risk", to: "/risk" },
    ],
  },
  {
    id: "liabilities",
    label: "Liabilities",
    icon: "trending_down",
    to: "/liabilities",
    tabs: [
      { label: "Overview", to: "/liabilities", exact: true },
      { label: "Credit Cards", to: "/credit-cards" },
      { label: "Loans", to: "/loans" },
    ],
  },
  {
    id: "operations",
    label: "Data Hub",
    icon: "settings_applications",
    to: "/operations",
    tabs: [
      { label: "Overview", to: "/operations", exact: true },
      { label: "Import Statements", to: "/ingest" },
      { label: "Add Accounts", to: "/accounts/new" },
      { label: "Add Platforms", to: "/platforms" },
      { label: "Add Crypto Wallets", to: "/crypto", exact: true },
      { label: "Refresh Market Data", to: "/market-data" },
      { label: "Author Ingestion", to: "/author-ingestion" },
    ],
  },
  {
    id: "intelligence",
    label: "Research",
    icon: "insights",
    to: "/intelligence",
    matchPaths: ["/alerts"],
    tabs: [
      { label: "Overview", to: "/intelligence", exact: true },
      { label: "AI Sage", to: "/ai-sage" },
      { label: "Author Library", to: "/author-library" },
      { label: "Companies", to: "/companies" },
      { label: "Alerts", to: "/alerts", hidden: true },
    ],
  },
];

export const UTILITY_NAV_ITEMS: UtilityNavItem[] = [
  { label: "Alerts", to: "/alerts", badgeKey: "alerts" },
];

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
