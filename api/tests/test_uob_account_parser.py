from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.ingestion.parsers import ParseResult
from app.ingestion.parsers.uob_account_xls_v1 import (
    ParsedRow,
    UOB_DEFAULT_CURRENCY,
    _collapse_rows,
    _classify_transaction,
    _extract_metadata,
    _select_balance_row,
    parse_uob_account_xls,
)


def _fixture_path() -> Path:
    fixture_name = "UOB_ACC_TXN_History_09032026225218.xls"
    candidates = [
        Path("/app/data/fixtures") / fixture_name,
        Path(__file__).resolve().parents[2] / "data" / "fixtures" / fixture_name,
        Path(__file__).resolve().parents[1] / "data" / "fixtures" / fixture_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("/app/data/fixtures") / fixture_name


def test_uob_parser_extracts_transactions_and_balance():
    result = parse_uob_account_xls(str(_fixture_path()))

    assert isinstance(result, ParseResult)
    assert len(result.transactions) == 3
    assert result.section_counts == {"transactions": 3}
    assert len(result.positions) == 1
    assert all(tx["currency"] == "SGD" for tx in result.transactions)
    assert Counter(tx["type"] for tx in result.transactions) == {
        "EXPENSE": 1,
        "INCOME": 1,
        "TRANSFER": 1,
    }
    assert sorted(tx["amount"] for tx in result.transactions) == [-1294.92, -321.84, 4600.0]


def test_uob_parser_classifies_transfers():
    result = parse_uob_account_xls(str(_fixture_path()))

    transfer_rows = [
        tx for tx in result.transactions if "UOB CARD CENTRE" in (tx.get("notes") or "")
    ]
    assert len(transfer_rows) == 1
    assert transfer_rows[0]["type"] == "TRANSFER"
    assert transfer_rows[0]["amount"] == -321.84


def test_uob_parser_extracts_cash_position():
    result = parse_uob_account_xls(str(_fixture_path()))

    assert result.positions == [
        {
            "symbol": "SGD",
            "name": "SGD Cash",
            "asset_class": "CASH",
            "currency": "SGD",
            "quantity": 97601.67,
            "avg_cost": 1.0,
            "cost_basis_base": 97601.67,
            "as_of": result.positions[0]["as_of"],
        }
    ]
    assert result.positions[0]["as_of"].date().isoformat() == "2026-03-09"


def test_uob_parser_date_parsing():
    result = parse_uob_account_xls(str(_fixture_path()))

    assert [tx["ts"].date().isoformat() for tx in result.transactions] == [
        "2026-03-04",
        "2026-03-04",
        "2026-03-02",
    ]


def test_uob_parser_empty_file(tmp_path: Path):
    fixture = tmp_path / "empty.xls"
    fixture.write_bytes(b"")

    result = parse_uob_account_xls(str(fixture))
    assert result.transactions == []
    assert result.positions == []
    assert result.section_counts == {"transactions": 0}


def test_uob_parser_handles_multiline_descriptions():
    result = parse_uob_account_xls(str(_fixture_path()))

    notes = [tx["notes"] for tx in result.transactions]
    assert any("4265 884038083159" in (note or "") for note in notes)
    assert any("NTUC MY FIRST SKOOL" in (note or "") for note in notes)
    assert any("SI SALARY" in (note or "") for note in notes)


def test_uob_parser_merges_continuation_row_amounts_into_parent_transaction():
    df = pd.DataFrame(
        [
            {
                "Transaction Date": "04 Mar 2026",
                "Transaction Description": "PAYNOW",
                "Withdrawal": None,
                "Deposit": None,
                "Available Balance": None,
            },
            {
                "Transaction Date": None,
                "Transaction Description": "NTUC MY FIRST SKOOL",
                "Withdrawal": "1,294.92",
                "Deposit": None,
                "Available Balance": "97,601.67",
            },
        ]
    )

    grouped = _collapse_rows(
        df,
        {
            "transaction date": "Transaction Date",
            "transaction description": "Transaction Description",
            "withdrawal": "Withdrawal",
            "deposit": "Deposit",
            "available balance": "Available Balance",
        },
    )

    assert len(grouped) == 1
    assert grouped[0].description == "PAYNOW\nNTUC MY FIRST SKOOL"
    assert grouped[0].withdrawal == 1294.92
    assert grouped[0].balance == 97601.67


def test_uob_parser_selects_latest_balance_row_even_if_middle_candidate():
    early = ParsedRow(
        row_index=1,
        ts=datetime(2026, 3, 1, tzinfo=timezone.utc),
        description="early",
        withdrawal=10.0,
        deposit=None,
        balance=100.0,
    )
    latest = ParsedRow(
        row_index=2,
        ts=datetime(2026, 3, 9, tzinfo=timezone.utc),
        description="latest",
        withdrawal=None,
        deposit=25.0,
        balance=225.0,
    )
    trailing = ParsedRow(
        row_index=3,
        ts=datetime(2026, 3, 4, tzinfo=timezone.utc),
        description="trailing",
        withdrawal=5.0,
        deposit=None,
        balance=180.0,
    )

    assert _select_balance_row([early, latest, trailing]) == latest


def test_uob_parser_falls_back_to_default_currency_when_metadata_missing():
    df = pd.DataFrame(
        [
            ["Account Number:", "123-456"],
            ["Account Type:", "One Account"],
            ["Statement Period:", "01 Mar 2026 to 09 Mar 2026"],
            [
                "Transaction Date",
                "Transaction Description",
                "Withdrawal",
                "Deposit",
                "Available Balance",
            ],
        ]
    )

    metadata = _extract_metadata(df, header_row=3)

    assert metadata["currency"] == UOB_DEFAULT_CURRENCY


def test_uob_parser_does_not_treat_generic_transfer_word_as_transfer():
    tx_type, category = _classify_transaction(-42.5, "Transfer Learning School")

    assert tx_type == "EXPENSE"
    assert category == "Bank::Withdrawal"
