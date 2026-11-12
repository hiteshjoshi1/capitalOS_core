"""#410 (U30): money into brokers with no cash record, estimated from holdings changes."""
from decimal import Decimal

from app.valuation.bridge import _broker_money, _item, _platform_keywords


def _trades(buys: str, sales: str = "0"):
    return {"buys": Decimal(buys), "sales": Decimal(sales), "rows": [_item("X", Decimal(buys) + Decimal(sales), "bought")]}


def test_keywords_name_the_broker_not_the_bank():
    assert _platform_keywords("DBS_VICKERS") == ["VICKERS"]
    assert _platform_keywords("SHAREKHAN") == ["SHAREKHAN"]
    assert _platform_keywords("DBS") == []  # a bank's code alone would match its own rows


def test_buys_with_no_bank_row_are_new_money():
    total, parts = _broker_money({"SHAREKHAN": _trades("500")}, [])
    assert total == Decimal("500") and parts[0]["key"] == "broker:SHAREKHAN"
    assert sum(i["amount"] for i in parts[0]["items"]) == parts[0]["amount"]


def test_a_transfer_from_your_bank_naming_the_broker_is_not_new_money():
    outflows = [
        {"text": "FAST TRANSFER DBS VICKERS SECURITIES", "base": Decimal("-480"), "account": "DBS", "day": None},
        {"text": "NTUC FAIRPRICE", "base": Decimal("-30"), "account": "DBS", "day": None},
    ]
    total, parts = _broker_money({"DBS_VICKERS": _trades("500")}, outflows)
    assert total == Decimal("20")  # 500 bought, 480 of it paid from DBS
    assert parts[0]["amount"] == Decimal("20")
    assert any("Paid in from your own accounts (1 transfer(s))" == i["label"] for i in parts[0]["items"])


def test_a_bank_row_counts_for_one_broker_only():
    outflows = [{"text": "SHAREKHAN VICKERS", "base": Decimal("-100"), "account": "DBS", "day": None}]
    total, parts = _broker_money({"DBS_VICKERS": _trades("100"), "SHAREKHAN": _trades("100")}, outflows)
    assert total == Decimal("100")
    assert sorted(p["amount"] for p in parts) == [Decimal("0"), Decimal("100")]


def test_sales_are_money_out():
    total, _parts = _broker_money({"SHAREKHAN": _trades("0", "-250")}, [])
    assert total == Decimal("-250")
