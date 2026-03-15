from pydantic import BaseModel


class CategoryTaxonomyOut(BaseModel):
    id: int
    code: str
    name: str
    parent_id: int | None = None
    display_order: int


class CategoryRuleCreate(BaseModel):
    name: str
    priority: int
    merchant_pattern: str | None = None
    description_pattern: str | None = None
    source_category_pattern: str | None = None
    txn_type: str | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    target_category_id: int
    active: bool = True


class CategoryRuleUpdate(BaseModel):
    name: str | None = None
    priority: int | None = None
    merchant_pattern: str | None = None
    description_pattern: str | None = None
    source_category_pattern: str | None = None
    txn_type: str | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    target_category_id: int | None = None
    active: bool | None = None


class CategoryRuleOut(BaseModel):
    id: int
    name: str
    priority: int
    merchant_pattern: str | None = None
    description_pattern: str | None = None
    source_category_pattern: str | None = None
    txn_type: str | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    target_category_id: int
    target_category_code: str
    target_category_name: str
    active: bool


class CategoryOverrideCreate(BaseModel):
    transaction_id: int
    category_id: int


class CategoryOverrideOut(BaseModel):
    id: int
    transaction_id: int
    category_id: int
    category_name: str
    source: str
    rule_id: int | None = None


class CategoryResolutionOut(BaseModel):
    transaction_id: int
    raw_category: str | None = None
    override_category: str | None = None
    resolved_category: str
    source: str
    rule_id: int | None = None
    rule_name: str | None = None


class UnmappedTransactionOut(BaseModel):
    transaction_id: int
    ts: str
    account_id: int
    account_name: str
    amount: float
    currency: str
    type: str
    raw_category: str | None = None
    merchant_counterparty: str | None = None
    notes: str | None = None


class BackfillResultOut(BaseModel):
    created: int
    updated: int
