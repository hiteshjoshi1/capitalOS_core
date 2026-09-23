"""One-off backfill: re-run the (now-fixed) DBS Vickers / Sharekhan holdings
parsers against their already-stored raw files, so portfolio_position_snapshots
rows written before the cost-basis/market-price swap fix get replaced with
correct values.

Safe to re-run: run_upload_canonical_adapter clears and replaces the existing
canonical facts for the same (broker_account_id, report_date) before writing.
"""
from __future__ import annotations

import hashlib
import sys

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.session import engine
from app.ingestion.parsers.dbs_vickers_holdings_xls_v1 import parse_dbs_vickers_holdings_xls
from app.ingestion.parsers.sharekhan_holdings_xls_v1 import parse_sharekhan_holdings_xls
from app.portfolio.upload_canonical import run_upload_canonical_adapter

PARSERS = {
    "DBS_VICKERS": parse_dbs_vickers_holdings_xls,
    "SHAREKHAN": parse_sharekhan_holdings_xls,
}


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        rows = db.execute(
            text(
                """
                SELECT rd.id AS raw_document_id, rd.broker_account_id, rd.storage_path,
                       rd.report_date_to, ba.legacy_account_id, bc.platform_code
                FROM raw_broker_documents rd
                JOIN broker_accounts ba ON ba.id = rd.broker_account_id
                JOIN broker_connections bc ON bc.id = ba.connection_id
                WHERE bc.platform_code IN ('DBS_VICKERS', 'SHAREKHAN')
                  AND rd.source_type IN ('dbs_vickers_upload', 'sharekhan_upload')
                ORDER BY rd.broker_account_id, rd.id
                """
            )
        ).mappings().all()

        for row in rows:
            platform = row["platform_code"]
            parser = PARSERS[platform]
            path = row["storage_path"]
            legacy_account_id = row["legacy_account_id"]
            report_date = row["report_date_to"]

            user_id = db.execute(
                text("SELECT user_id FROM accounts WHERE id = :aid"),
                {"aid": legacy_account_id},
            ).scalar()

            parse_result = parser(path)
            if not parse_result.positions:
                print(f"skip (no positions parsed): {path}")
                continue

            # _resolve_report_date() falls back to today() when parser_meta has
            # no date — pin it to the original upload's report date so this
            # replaces the existing (broker_account_id, report_date) snapshot
            # instead of creating a new one dated today.
            parse_result.parser_meta = dict(parse_result.parser_meta or {})
            parse_result.parser_meta["report_date"] = report_date

            result = run_upload_canonical_adapter(
                db,
                current_user_id=user_id,
                legacy_account_id=legacy_account_id,
                platform_code=platform,
                parse_result=parse_result,
                stored_path=path,
                file_sha256=_sha256_file(path),
            )
            db.commit()
            print(f"reprocessed {path} (account_id={legacy_account_id}, platform={platform}): {result}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
    sys.exit(0)
