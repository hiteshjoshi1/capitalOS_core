"""Generate deterministic, synthetic ingestion fixtures with no personal data."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook


FIXTURE_DIR = Path(__file__).resolve().parent
FIXED_ZIP_TIMESTAMP = (2000, 1, 1, 0, 0, 0)


def _write_csv(name: str, rows: list[list[object]]) -> None:
    with (FIXTURE_DIR / name).open("w", encoding="utf-8", newline="") as output:
        csv.writer(output, lineterminator="\n").writerows(rows)


def _save_deterministic_workbook(workbook: Workbook, name: str) -> None:
    workbook.properties.creator = "CapitalOS Test Suite"
    workbook.properties.lastModifiedBy = "CapitalOS Test Suite"
    workbook.properties.title = "Synthetic ingestion fixture"
    workbook.properties.description = "Deterministic test data; no personal data"
    workbook.properties.created = datetime(2000, 1, 1)
    workbook.properties.modified = datetime(2000, 1, 1)

    target = FIXTURE_DIR / name
    with NamedTemporaryFile(suffix=".xlsx") as temporary:
        workbook.save(temporary.name)
        with ZipFile(temporary.name, "r") as source, ZipFile(
            target, "w", compression=ZIP_DEFLATED
        ) as output:
            for member_name in sorted(source.namelist()):
                info = ZipInfo(member_name, FIXED_ZIP_TIMESTAMP)
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                output.writestr(info, source.read(member_name))


def _generate_citi_credit_card() -> None:
    test_card_number = "4111111111111111"
    rows: list[list[object]] = []

    expense_descriptions = [
        "TEST GROCERY STORE",
        "TEST CAFE",
        "TEST TRANSIT",
        "TEST PHARMACY",
        "TEST BOOK STORE",
        "TEST HARDWARE STORE",
        "TEST UTILITY",
        "TEST MARKETPLACE",
        "TEST RESTAURANT",
        "TEST OFFICE SUPPLY",
    ]
    for index in range(42):
        day = 6 - (index % 6)
        description = f"{expense_descriptions[index % len(expense_descriptions)]} #{index + 1:02d}"
        if index == 1:
            description = "TEST CLOUD SERVICE #02 USD 21.80"
        elif index == 2:
            description = "TEST MEETING SERVICE #03 USD 12.00"
        rows.append(
            [
                f"{day:02d}/03/2026",
                description,
                f"-{10 + index / 10:.2f}",
                "",
                test_card_number,
            ]
        )

    rows.extend(
        [
            ["28/02/2026", "PAYMENT - THANK YOU TEST A", "500.00", "", test_card_number],
            ["28/01/2026", "PAYMENT - THANK YOU TEST B", "400.00", "", test_card_number],
            ["27/02/2026", "LATE CHARGE FEE TEST", "-25.00", "", test_card_number],
            ["27/01/2026", "LATE CHARGE FEE REVERSAL TEST", "25.00", "", test_card_number],
            ["26/02/2026", "BILLED FINANCE CHARGES TEST A", "-18.50", "", test_card_number],
            ["26/01/2026", "BILLED FINANCE CHARGES TEST B", "-7.25", "", test_card_number],
            ["25/02/2026", "RTL INT CRED ADJ TEST A", "18.50", "", test_card_number],
            ["25/01/2026", "RTL INT CRED ADJ TEST B", "7.25", "", test_card_number],
            ["24/02/2026", "TEST PURCHASE REFUND", "12.34", "", test_card_number],
        ]
    )
    _write_csv("citi_credit_card_sample.csv", rows)


def _generate_dbs_credit_card() -> None:
    rows: list[list[object]] = [
        [
            "Card Transaction Details For:",
            "DBS/POSB MasterCard Platinum 5555-5555-5555-4444",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        ["Transactions As At:", "04 Jul 2026", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", ""],
        ["Credit Limit:", "SGD 10000.00", "", "", "", "", "", ""],
        ["Available Limit:", "SGD 9739.44", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", ""],
        [
            "Transaction Date",
            "Transaction Posting Date",
            "Transaction Description",
            "Transaction Type",
            "Payment Type",
            "Transaction Status",
            "Debit Amount",
            "Credit Amount",
        ],
        [
            "14 Jan 2026",
            "15 Jan 2026",
            "FINANCE CHARGES TEST",
            "Interest",
            "",
            "Posted",
            "16.73",
            "",
        ],
        [
            "15 Jan 2026",
            "16 Jan 2026",
            "GST @ 9%",
            "Goods and Services Tax",
            "",
            "Posted",
            "16.20",
            "",
        ],
        [
            "16 Jan 2026",
            "17 Jan 2026",
            "TEST ANNUAL FEE",
            "Fees",
            "",
            "Posted",
            "12.00",
            "",
        ],
        [
            "17 Jan 2026",
            "18 Jan 2026",
            "TEST SERVICE CHARGE",
            "Charges",
            "",
            "Posted",
            "8.00",
            "",
        ],
    ]
    for index in range(7):
        rows.append(
            [
                f"{18 + index:02d} Jan 2026",
                f"{19 + index:02d} Jan 2026",
                f"NTUC FAIRPRICE TEST STORE #{index + 1}",
                "Retail Purchase",
                "Contactless",
                "Posted",
                f"{20 + index:.2f}",
                "",
            ]
        )
    _write_csv("transaction_history_04072026_105429.csv", rows)


def _generate_ocbc_account() -> None:
    rows: list[list[object]] = [
        ["Account details for:", "360 Account 000-000000-001"],
        ["Available Balance", "25000.00"],
        ["Ledger Balance", "25000.00"],
        ["Transaction date", "Value date", "Description", "Withdrawals(SGD)", "Deposits(SGD)"],
        ["10/03/2026", "10/03/2026", "BONUS INTEREST TEST", "", "7.27"],
        ["09/03/2026", "09/03/2026", "INTEREST CREDIT TEST", "", "2.15"],
        ["08/03/2026", "08/03/2026", "NETS TEST PURCHASE", "25.50", ""],
        ["07/03/2026", "07/03/2026", "FAST PAYMENT TEST RECIPIENT", "125.00", ""],
        ["06/03/2026", "06/03/2026", "FUND TRANSFER TEST SAVINGS", "200.00", ""],
        ["05/03/2026", "05/03/2026", "IBG GIRO TEST BILL", "75.00", ""],
        ["04/03/2026", "04/03/2026", "CASH WITHDRAWAL TEST ATM", "100.00", ""],
        ["03/03/2026", "03/03/2026", "IBG GIRO SI SALARY SAMPLE EMPLOYEE OTHR", "", "5000.00"],
        ["02/03/2026", "02/03/2026", "TEST GROCERY PURCHASE", "65.25", ""],
        ["01/03/2026", "01/03/2026", "TEST CAFE PURCHASE", "12.40", ""],
        ["28/02/2026", "28/02/2026", "PAYNOW TEST FRIEND", "30.00", ""],
        ["27/02/2026", "27/02/2026", "TEST PHARMACY PURCHASE", "18.90", ""],
        ["26/02/2026", "26/02/2026", "TEST TRANSPORT PURCHASE", "9.50", ""],
        ["25/02/2026", "25/02/2026", "TEST UTILITY PAYMENT", "80.00", ""],
        ["24/02/2026", "24/02/2026", "TEST BOOK PURCHASE", "22.00", ""],
        ["23/02/2026", "23/02/2026", "TEST MARKET PURCHASE", "31.10", ""],
        ["22/02/2026", "22/02/2026", "TEST REFUND", "", "15.00"],
        ["21/02/2026", "21/02/2026", "TEST OFFICE PURCHASE", "44.00", ""],
        ["20/02/2026", "20/02/2026", "TEST SUBSCRIPTION", "11.99", ""],
        ["19/02/2026", "19/02/2026", "TEST DINING PURCHASE", "27.80", ""],
    ]
    _write_csv("ocbc_TransactionHistory_20260313165630.csv", rows)


def _generate_uob_account() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet0"
    rows: list[list[object]] = [
        ["Account Number:", "000-000-001", "SGD"],
        ["Account Type:", "UOB TEST ACCOUNT"],
        ["Statement Period:", "01 Mar 2026 to 09 Mar 2026"],
        ["Export Type:", "Synthetic test fixture"],
        ["Currency:", "SGD"],
        ["Notice:", "No personal data"],
        ["Generated For:", "CapitalOS tests"],
        [
            "Transaction Date",
            "Transaction Description",
            "Withdrawal",
            "Deposit",
            "Available Balance",
        ],
        ["09 Mar 2026", "SALARY SAMPLE EMPLOYER", None, 5000.00, 100000.00],
        ["06 Mar 2026", "CARD PURCHASE", None, None, None],
        [None, "SAMPLE EDUCATION CENTRE", 1200.00, None, 98800.00],
        ["04 Mar 2026", "FAST TRANSFER", None, None, None],
        [None, "UOB CARD CENTRE TEST CARD", 300.00, None, 98500.00],
    ]
    for row in rows:
        sheet.append(row)
    _save_deterministic_workbook(workbook, "UOB_ACC_TXN_History_09032026225218.xls")


def _generate_uob_credit_card() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet0"
    rows: list[list[object]] = [
        ["Account Number:", "4111111111111111", "SGD"],
        ["Account Type:", "UOB TEST CARD"],
        ["Statement Date:", "12 Feb 2026"],
        ["Statement Balance:", "321.84", "SGD"],
        ["Export Type:", "Synthetic test fixture"],
        ["Currency:", "SGD"],
        ["Notice:", "No personal data"],
        ["Generated For:", "CapitalOS tests"],
        ["Record Type:", "Card transactions"],
        [
            "Transaction Date",
            "Posting Date",
            "Description",
            "Foreign Currency Type",
            "Transaction Amount(Foreign)",
            "Local Currency Type",
            "Transaction Amount(Local)",
        ],
        [
            "06 Feb 2026",
            "09 Feb 2026",
            "TEST CAFE SINGAPORE SG\nREF NO: TEST000001",
            None,
            None,
            "SGD",
            19.62,
        ],
        ["05 Feb 2026", "06 Feb 2026", "NTUC FAIRPRICE TEST STORE", None, None, "SGD", 24.50],
        ["04 Feb 2026", "05 Feb 2026", "TEST TRANSIT PURCHASE", None, None, "SGD", 8.25],
        ["03 Feb 2026", "04 Feb 2026", "TEST HARDWARE STORE", None, None, "SGD", 13.50],
        ["02 Feb 2026", "03 Feb 2026", "TEST BOOK STORE", None, None, "SGD", 18.00],
        ["01 Feb 2026", "02 Feb 2026", "TEST PHARMACY", None, None, "SGD", 15.75],
        ["31 Jan 2026", "01 Feb 2026", "TEST MARKETPLACE", None, None, "SGD", 32.10],
        ["30 Jan 2026", "31 Jan 2026", "TEST RESTAURANT", None, None, "SGD", 27.40],
        [
            "29 Jan 2026",
            "30 Jan 2026",
            "TEST CLOUD SERVICE USD 10.00\nREF NO: TEST000008",
            "USD",
            10.00,
            "SGD",
            45.00,
        ],
        ["28 Jan 2026", "29 Jan 2026", "TEST OFFICE SUPPLY", None, None, "SGD", 11.25],
        ["27 Jan 2026", "28 Jan 2026", "GIRO PAYMENT", None, None, "SGD", -424.03],
    ]
    for row in rows:
        sheet.append(row)
    _save_deterministic_workbook(workbook, "UOB_CC_TXN_History_09032026222725.xls")


def main() -> None:
    _generate_citi_credit_card()
    _generate_dbs_credit_card()
    _generate_ocbc_account()
    _generate_uob_account()
    _generate_uob_credit_card()


if __name__ == "__main__":
    main()
