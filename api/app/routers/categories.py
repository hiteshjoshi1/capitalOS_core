from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.category_engine import apply_rules, resolve_category
from app.db.session import get_db
from app.models.category import CategoryRule, CategoryTaxonomy
from app.schemas.category import (
    BackfillResultOut,
    CategoryOverrideCreate,
    CategoryResolutionOut,
    CategoryRuleCreate,
    CategoryRuleOut,
    CategoryRuleUpdate,
    CategoryTaxonomyOut,
    UnmappedTransactionOut,
)

router = APIRouter(prefix="/categories", tags=["categories"], dependencies=[Depends(require_current_user)])

VALID_TXN_TYPES = {
    "INCOME",
    "EXPENSE",
    "TRANSFER",
    "BUY",
    "SELL",
    "FEE",
    "TAX",
    "INTEREST",
}


def _parse_month(month: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid month format. Use YYYY-MM, e.g. 2026-02",
        ) from exc
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _normalize_pattern(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _validate_target_category(db: Session, category_id: int) -> None:
    exists = db.query(CategoryTaxonomy).filter(CategoryTaxonomy.id == category_id).one_or_none()
    if exists is None:
        raise HTTPException(status_code=400, detail="target_category_id not found")


def _validate_transaction(db: Session, transaction_id: int, current_user_id: int) -> None:
    row = db.execute(
        text(
            """
            SELECT t.id
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.id = :transaction_id
              AND """
            + account_scope_sql("a")
            + """
            LIMIT 1
            """
        ),
        {"transaction_id": transaction_id, "current_user_id": current_user_id},
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail="transaction_id not found")


def _validate_rule_values(payload: dict) -> dict:
    if "name" in payload and payload["name"] is not None:
        payload["name"] = payload["name"].strip()
        if not payload["name"]:
            raise HTTPException(status_code=400, detail="name is required")

    for field in ("merchant_pattern", "description_pattern", "source_category_pattern"):
        if field in payload:
            payload[field] = _normalize_pattern(payload[field])

    if "txn_type" in payload and payload["txn_type"] is not None:
        txn_type = payload["txn_type"].strip().upper()
        if not txn_type:
            payload["txn_type"] = None
        elif txn_type not in VALID_TXN_TYPES:
            raise HTTPException(status_code=400, detail="invalid txn_type")
        else:
            payload["txn_type"] = txn_type

    min_amount = payload.get("min_amount")
    max_amount = payload.get("max_amount")
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise HTTPException(status_code=400, detail="min_amount cannot exceed max_amount")

    return payload


def _rule_out(db: Session, rule_id: int) -> CategoryRuleOut:
    row = db.execute(
        text(
            """
            SELECT
              r.id,
              r.name,
              r.priority,
              r.merchant_pattern,
              r.description_pattern,
              r.source_category_pattern,
              r.txn_type,
              r.min_amount,
              r.max_amount,
              r.target_category_id,
              ct.code AS target_category_code,
              ct.name AS target_category_name,
              r.active
            FROM category_rules r
            JOIN category_taxonomy ct ON ct.id = r.target_category_id
            WHERE r.id = :rule_id
            LIMIT 1
            """
        ),
        {"rule_id": rule_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return CategoryRuleOut(
        id=int(row["id"]),
        name=row["name"],
        priority=int(row["priority"]),
        merchant_pattern=row["merchant_pattern"],
        description_pattern=row["description_pattern"],
        source_category_pattern=row["source_category_pattern"],
        txn_type=row["txn_type"],
        min_amount=float(row["min_amount"]) if row["min_amount"] is not None else None,
        max_amount=float(row["max_amount"]) if row["max_amount"] is not None else None,
        target_category_id=int(row["target_category_id"]),
        target_category_code=row["target_category_code"],
        target_category_name=row["target_category_name"],
        active=bool(row["active"]),
    )


@router.get("", response_model=list[CategoryTaxonomyOut])
def list_categories(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            """
            SELECT id, code, name, parent_id, display_order
            FROM category_taxonomy
            ORDER BY display_order, id
            """
        )
    ).mappings().all()
    return [
        CategoryTaxonomyOut(
            id=int(row["id"]),
            code=row["code"],
            name=row["name"],
            parent_id=int(row["parent_id"]) if row["parent_id"] is not None else None,
            display_order=int(row["display_order"]),
        )
        for row in rows
    ]


@router.get("/rules", response_model=list[CategoryRuleOut])
def list_rules(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            """
            SELECT
              r.id,
              r.name,
              r.priority,
              r.merchant_pattern,
              r.description_pattern,
              r.source_category_pattern,
              r.txn_type,
              r.min_amount,
              r.max_amount,
              r.target_category_id,
              ct.code AS target_category_code,
              ct.name AS target_category_name,
              r.active
            FROM category_rules r
            JOIN category_taxonomy ct ON ct.id = r.target_category_id
            ORDER BY r.priority, r.id
            """
        )
    ).mappings().all()
    return [
        CategoryRuleOut(
            id=int(row["id"]),
            name=row["name"],
            priority=int(row["priority"]),
            merchant_pattern=row["merchant_pattern"],
            description_pattern=row["description_pattern"],
            source_category_pattern=row["source_category_pattern"],
            txn_type=row["txn_type"],
            min_amount=float(row["min_amount"]) if row["min_amount"] is not None else None,
            max_amount=float(row["max_amount"]) if row["max_amount"] is not None else None,
            target_category_id=int(row["target_category_id"]),
            target_category_code=row["target_category_code"],
            target_category_name=row["target_category_name"],
            active=bool(row["active"]),
        )
        for row in rows
    ]


@router.post("/rules", response_model=CategoryRuleOut)
def create_rule(payload: CategoryRuleCreate, db: Session = Depends(get_db)):
    data = _validate_rule_values(payload.model_dump())
    _validate_target_category(db, data["target_category_id"])

    rule = CategoryRule(**data)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_out(db, int(rule.id))


@router.put("/rules/{rule_id}", response_model=CategoryRuleOut)
def update_rule(rule_id: int, payload: CategoryRuleUpdate, db: Session = Depends(get_db)):
    rule = db.query(CategoryRule).filter(CategoryRule.id == rule_id).one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")

    data = _validate_rule_values(payload.model_dump(exclude_unset=True))
    if "target_category_id" in data and data["target_category_id"] is not None:
        _validate_target_category(db, data["target_category_id"])

    for key, value in data.items():
        setattr(rule, key, value)
    rule.updated_at = datetime.now(tz=timezone.utc)

    db.add(rule)
    db.commit()
    return _rule_out(db, rule_id)


@router.delete("/rules/{rule_id}", response_model=CategoryRuleOut)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(CategoryRule).filter(CategoryRule.id == rule_id).one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")

    rule.active = False
    rule.updated_at = datetime.now(tz=timezone.utc)
    db.add(rule)
    db.commit()
    return _rule_out(db, rule_id)


@router.get("/unmapped", response_model=list[UnmappedTransactionOut])
def list_unmapped_transactions(
    month: str = Query(..., description="YYYY-MM"),
    account_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    start, end = _parse_month(month)
    sql = """
        SELECT
          t.id AS transaction_id,
          t.ts,
          t.account_id,
          a.name AS account_name,
          t.amount,
          t.currency,
          t.type,
          t.category AS raw_category,
          t.merchant_counterparty,
          t.notes
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN category_overrides co ON co.transaction_id = t.id
        WHERE t.ts >= :start
          AND t.ts < :end
          AND """
    sql += account_scope_sql("a")
    sql += """
          AND co.id IS NULL
          AND (
            t.category IS NULL
            OR TRIM(t.category) = ''
            OR LOWER(TRIM(t.category)) = 'uncategorized'
          )
    """
    params: dict[str, object] = {"start": start, "end": end}
    if account_id is not None:
        sql += " AND t.account_id = :account_id"
        params["account_id"] = account_id
    params["current_user_id"] = current_user.id
    sql += " ORDER BY t.ts DESC, t.id DESC"

    rows = db.execute(text(sql), params).mappings().all()
    return [
        UnmappedTransactionOut(
            transaction_id=int(row["transaction_id"]),
            ts=str(row["ts"]),
            account_id=int(row["account_id"]),
            account_name=row["account_name"],
            amount=float(row["amount"]),
            currency=row["currency"],
            type=row["type"],
            raw_category=row["raw_category"],
            merchant_counterparty=row["merchant_counterparty"],
            notes=row["notes"],
        )
        for row in rows
    ]


@router.post("/override", response_model=CategoryResolutionOut)
def apply_manual_override(
    payload: CategoryOverrideCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    _validate_transaction(db, payload.transaction_id, current_user.id)
    _validate_target_category(db, payload.category_id)

    existing = db.execute(
        text(
            """
            SELECT id
            FROM category_overrides
            WHERE transaction_id = :transaction_id
            LIMIT 1
            """
        ),
        {"transaction_id": payload.transaction_id},
    ).mappings().first()

    if existing is None:
        db.execute(
            text(
                """
                INSERT INTO category_overrides (transaction_id, category_id, source, rule_id)
                VALUES (:transaction_id, :category_id, 'manual', NULL)
                """
            ),
            {
                "transaction_id": payload.transaction_id,
                "category_id": payload.category_id,
            },
        )
    else:
        db.execute(
            text(
                """
                UPDATE category_overrides
                SET category_id = :category_id,
                    source = 'manual',
                    rule_id = NULL,
                    updated_at = :updated_at
                WHERE id = :id
                """
            ),
            {
                "id": int(existing["id"]),
                "category_id": payload.category_id,
                "updated_at": datetime.now(tz=timezone.utc),
            },
        )

    db.commit()
    return CategoryResolutionOut(**resolve_category(db, payload.transaction_id))


@router.get("/resolve/{transaction_id}", response_model=CategoryResolutionOut)
def resolve_transaction_category(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    _validate_transaction(db, transaction_id, current_user.id)
    return CategoryResolutionOut(**resolve_category(db, transaction_id))


@router.post("/backfill", response_model=BackfillResultOut)
def backfill_categories(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    tx_rows = db.execute(
        text(
            """
            SELECT t.id
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user.id},
    ).mappings().all()
    tx_ids = [int(row["id"]) for row in tx_rows]
    result = apply_rules(db, tx_ids)
    return BackfillResultOut(created=result.created, updated=result.updated)
