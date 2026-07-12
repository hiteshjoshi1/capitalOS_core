"""
Keyword-based merchant categorization for credit card purchases.

Classifies purchase transactions into human-readable categories by matching
merchant/counterparty text against keyword lists. Returns a friendly category
string that can be stored directly as the raw ``category`` field, making
``resolved_category`` meaningful without a separate backfill pass.

Rules are checked in order; more specific patterns must appear before broader
ones (e.g. "GRAB FOOD" before "GRAB").
"""
from __future__ import annotations

# Each entry is (keywords_to_match, category_string).
# The first matching rule wins. Keywords are matched case-insensitively.
_RULES: list[tuple[tuple[str, ...], str]] = [
    # --- Food delivery (must come before generic GRAB / AMAZON rules) ---
    (
        ("GRAB FOOD", "GRABFOOD", "FOODPANDA", "FOOD PANDA",
         "DELIVEROO", "UBER EATS", "UBEREATS"),
        "Dining",
    ),
    # --- Groceries ---
    (
        ("SHENG SIONG", "NTUC FAIRPRICE", "NTUC FP", "FAIRPRICE",
         "COLD STORAGE", "COLDSTORAGE", "GIANT HYPERMARKET", "GIANT SUPER",
         "SHENGSIONG", "REDMART", "RED MART", "DON DON DONKI", "DONKI",
         "PRIME SUPERMARKET", "JASON'S MARKET PLACE", "JASONSMKPL",
         "BENGAWAN SOLO"),
        "Groceries",
    ),
    # --- Dining / restaurants / cafes (after grocery, before generic AMAZON) ---
    (
        ("KOPITIAM", "HAWKER", "COFFEE BEAN", "STARBUCKS", "TIM HORTONS",
         "TOAST BOX", "OLD CHANG KEE", "MCDONALD", "KFC", "SUBWAY",
         "BURGER KING", "PIZZA HUT", "DOMINO", "PAPA JOHN",
         "CRYSTAL JADE", "PARADISE DYNASTY", "DIN TAI FUNG", "PUTIEN",
         "SAIZERIYA", "GENKI SUSHI", "SUSHI", "YAKUN", "KILLINEY",
         "BENGAWAN", "BENGAWA", "BENGAWANSOLO", "BENGAWAN BAKERY",
         "BREAD TALK", "BreadTalk", "PARIS BAGUETTE", "FOUR LEAVES",
         "BENGAWAN SOLO", "BENGAWAN"),
        "Dining",
    ),
    # --- Subscriptions / SaaS (before generic AMAZON / APPLE) ---
    (
        ("NETFLIX", "SPOTIFY", "APPLE.COM/BILL", "APPSTORE",
         "GOOGLE PLAY", "GOOGLE STORAGE", "ADOBE SYSTEMS", "ADOBE INC",
         "AMAZON PRIME", "AMAZON VIDEO", "DISNEY PLUS", "DISNEY+",
         "DISNEYPLUS", "HBO MAX", "HBOMAX", "YOUTUBE PREMIUM",
         "MICROSOFT 365", "MICROSOFT 36", "OFFICE 365", "XBOX GAME PASS",
         "DROPBOX", "CHATGPT", "OPENAI", "ZOOM VIDEO", "ZOOM.US",
         "GITHUB", "DIGITALOCEAN", "LINODE", "LASTPASS", "1PASSWORD",
         "CANVA", "FIGMA", "NOTION", "SLACK", "ASANA",
         "CIRCLES.LIFE", "SINGTEL TV", "STARHUB TV", "APPLE TV+",
         "APPLE MUSIC", "DEEZER", "TIDAL"),
        "Subscriptions",
    ),
    # --- Transport / rideshare (after food delivery) ---
    (
        ("GRAB", "GOJEK", "GO-JEK", "TADA ", "RYDE ",
         "COMFORT DELGRO", "COMFORTDELGRO", "COMFORT CAB",
         "BLUECAB", "EZ LINK", "EZLINK", "EZ-LINK",
         "TRANSIT LINK", "TRANSITLINK",
         "SMRT ", "SBS TRANSIT", "SBSTRANSIT",
         "CABCHARGE", "YELLOW CAB"),
        "Transport",
    ),
    # --- Travel ---
    (
        ("SINGAPORE AIRLINES", "SIA ", "SILKAIR", "SCOOT",
         "JETSTAR", "AIR ASIA", "AIRASIA", "CATHAY PACIFIC", "EMIRATES",
         "LUFTHANSA", "UNITED AIRLINES", "AMERICAN AIRLINES", "DELTA AIR",
         "BOOKING.COM", "HOTELS.COM", "EXPEDIA", "AGODA", "AIRBNB",
         "KLOOK", "CHANGI AIRPORT", "CHANGI RECOMMENDS",
         "SKYSCANNER", "KAYAK", "TRIP.COM", "CTRIP", "RENTALCARS",
         "HERTZ", "AVIS ", "ENTERPRISE RENT"),
        "Travel",
    ),
    # --- Shopping: online / retail (after subscriptions) ---
    (
        ("LAZADA", "SHOPEE", "AMAZON", "QXPRESS", "ZALORA", "ASOS",
         "TAOBAO", "ALIEXPRESS", "UNIQLO", "H&M ", "ZARA ", "COTTON ON",
         "COURTS ", "HARVEY NORMAN", "HARVEYNORMAN",
         "CHALLENGER ", "GAIN CITY", "BEST DENKI",
         "IKEA", "MUJI", "APPLE STORE", "SAMSUNG ", "SONY "),
        "Shopping",
    ),
    # --- Utilities / telco / services ---
    (
        ("SINGTEL", "STARHUB", " M1 ", "M1 LIMITED",
         "SP SERVICES", "SINGAPORE POWER",
         "PUB ", "SINGAPORE PUB",
         "TOWN COUNCIL", "SP GROUP"),
        "Utilities",
    ),
    # --- Medical / health ---
    (
        ("GUARDIAN PHARMACY", "WATSONS", "WATSON'S",
         "UNITY PHARMACY", "UNITY PHARMACY",
         "POLYCLINIC", "RAFFLES MEDICAL", "RAFFLES HOSPITAL",
         "PARKWAY HEALTH", "MOUNT ALVERNIA",
         "NUH", "SGH ", "SINGAPORE GENERAL",
         "NATIONAL UNIVERSITY HOSPITAL",
         "DENTAL", "DENTIST", "OPTOMETRY", "OPTICIAN",
         "CLINIC ", "PHARMACY "),
        "Medical",
    ),
]


def classify_merchant(description: str, merchant_counterparty: str | None = None) -> str:
    """Return a human-readable category for a credit card purchase.

    Checks *merchant_counterparty* first (more reliable), then falls back to
    searching the full *description*. Returns ``"CreditCard::Purchase"`` when
    no rule matches so the transaction still surfaces in the unmapped-filter.
    """
    search_text = " ".join(
        filter(None, [merchant_counterparty, description])
    ).upper()

    for keywords, category in _RULES:
        if any(kw.upper() in search_text for kw in keywords):
            return category

    return "CreditCard::Purchase"
