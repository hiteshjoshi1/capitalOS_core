from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


@dataclass
class BackfillResult:
    created: int = 0
    updated: int = 0


def _parser_fallback(raw_category: str | None) -> tuple[str, str]:
    normalized = (raw_category or "").strip()
    if normalized and normalized.lower() != "uncategorized":
        return normalized, "parser"
    return "Uncategorized", "uncategorized"


def _expanding_text(sql: str):
    return text(sql).bindparams(bindparam("transaction_ids", expanding=True))


def resolve_category(db: Session, transaction_id: int) -> dict:
    row = db.execute(
        text(
            """
            SELECT
              t.id AS transaction_id,
              t.category AS raw_category,
              ct.name AS override_category,
              co.source AS override_source,
              co.rule_id AS rule_id,
              cr.name AS rule_name
            FROM transactions t
            LEFT JOIN category_overrides co ON co.transaction_id = t.id
            LEFT JOIN category_taxonomy ct ON ct.id = co.category_id
            LEFT JOIN category_rules cr ON cr.id = co.rule_id
            WHERE t.id = :transaction_id
            LIMIT 1
            """
        ),
        {"transaction_id": transaction_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="transaction not found")

    if row["override_category"]:
        resolved_category = str(row["override_category"])
        source = str(row["override_source"])
    else:
        resolved_category, source = _parser_fallback(row["raw_category"])

    return {
        "transaction_id": int(row["transaction_id"]),
        "raw_category": row["raw_category"],
        "override_category": row["override_category"],
        "resolved_category": resolved_category,
        "source": source,
        "rule_id": int(row["rule_id"]) if row["rule_id"] is not None else None,
        "rule_name": row["rule_name"],
    }


def apply_rules(db: Session, transaction_ids: list[int] | None = None) -> BackfillResult:
    result = BackfillResult()
    params: dict[str, object] = {"manual_source": "manual", "active_true": True}

    eligible_sql = """
        SELECT t.id
        FROM transactions t
        LEFT JOIN category_overrides manual_override
          ON manual_override.transaction_id = t.id
         AND manual_override.source = :manual_source
        WHERE manual_override.id IS NULL
    """
    if transaction_ids is not None:
        if not transaction_ids:
            return result
        eligible_sql += " AND t.id IN :transaction_ids"
        eligible_query = _expanding_text(eligible_sql)
        params["transaction_ids"] = transaction_ids
    else:
        eligible_query = text(eligible_sql)

    eligible_rows = db.execute(eligible_query, params).mappings().all()
    eligible_ids = [int(row["id"]) for row in eligible_rows]
    if not eligible_ids:
        return result

    match_sql = """
        WITH ranked_matches AS (
          SELECT
            t.id AS transaction_id,
            r.id AS rule_id,
            r.target_category_id AS category_id,
            ROW_NUMBER() OVER (
              PARTITION BY t.id
              ORDER BY r.priority ASC, r.id ASC
            ) AS rule_rank
          FROM transactions t
          JOIN category_rules r ON r.active = :active_true
          LEFT JOIN category_overrides manual_override
            ON manual_override.transaction_id = t.id
           AND manual_override.source = :manual_source
          WHERE manual_override.id IS NULL
            AND t.id IN :transaction_ids
            AND (
              r.merchant_pattern IS NULL
              OR LOWER(COALESCE(t.merchant_counterparty, '')) LIKE LOWER(r.merchant_pattern)
            )
            AND (
              r.description_pattern IS NULL
              OR LOWER(COALESCE(t.notes, '')) LIKE LOWER(r.description_pattern)
            )
            AND (
              r.source_category_pattern IS NULL
              OR LOWER(COALESCE(t.category, '')) LIKE LOWER(r.source_category_pattern)
            )
            AND (
              r.txn_type IS NULL
              OR t.type = r.txn_type
            )
            AND (
              r.min_amount IS NULL
              OR t.amount >= r.min_amount
            )
            AND (
              r.max_amount IS NULL
              OR t.amount <= r.max_amount
            )
        )
        SELECT transaction_id, rule_id, category_id
        FROM ranked_matches
        WHERE rule_rank = 1
    """
    matched_rows = db.execute(
        _expanding_text(match_sql),
        {"transaction_ids": eligible_ids, "manual_source": "manual", "active_true": True},
    ).mappings().all()
    matched_by_transaction = {
        int(row["transaction_id"]): {
            "rule_id": int(row["rule_id"]),
            "category_id": int(row["category_id"]),
        }
        for row in matched_rows
    }

    existing_rule_rows = db.execute(
        _expanding_text(
            """
            SELECT id, transaction_id, category_id, rule_id
            FROM category_overrides
            WHERE source = 'rule'
              AND transaction_id IN :transaction_ids
            """
        ),
        {"transaction_ids": eligible_ids},
    ).mappings().all()
    existing_rule_overrides = {
        int(row["transaction_id"]): {
            "id": int(row["id"]),
            "category_id": int(row["category_id"]),
            "rule_id": int(row["rule_id"]) if row["rule_id"] is not None else None,
        }
        for row in existing_rule_rows
    }

    for tx_id, match in matched_by_transaction.items():
        existing = existing_rule_overrides.pop(tx_id, None)
        if existing is None:
            db.execute(
                text(
                    """
                    INSERT INTO category_overrides (transaction_id, category_id, source, rule_id)
                    VALUES (:transaction_id, :category_id, 'rule', :rule_id)
                    """
                ),
                {
                    "transaction_id": tx_id,
                    "category_id": match["category_id"],
                    "rule_id": match["rule_id"],
                },
            )
            result.created += 1
            continue

        if (
            existing["category_id"] == match["category_id"]
            and existing["rule_id"] == match["rule_id"]
        ):
            continue

        db.execute(
            text(
                """
                UPDATE category_overrides
                SET category_id = :category_id,
                    source = 'rule',
                    rule_id = :rule_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {
                "id": existing["id"],
                "category_id": match["category_id"],
                "rule_id": match["rule_id"],
            },
        )
        result.updated += 1

    stale_transaction_ids = list(existing_rule_overrides.keys())
    if stale_transaction_ids:
        db.execute(
            _expanding_text(
                """
                DELETE FROM category_overrides
                WHERE source = 'rule'
                  AND transaction_id IN :transaction_ids
                """
            ),
            {"transaction_ids": stale_transaction_ids},
        )

    db.commit()
    return result
