# PRD — Module 1: Personal Finance Control Plane (v1)

### Module A — Personal Financial Brain
Structured visibility into:
- portfolio across asset classes and geographies
- bank balances
- credit cards
- spending

Outputs:
- net worth
- asset allocation
- savings rate
- burn rate
- risk
Answers the question: What is my networth? How am I spending? What am I saving? 


## Overview

Module 1 establishes the foundational financial control plane for CapitalOS.

It provides a unified view of personal capital across cash, equities, and crypto, across geographies combined with spending visibility and historical trends.

This module is designed to answer fundamental questions:

- What is my current net worth?
- How is my capital allocated?
- Where is risk concentrated?
- How much am I spending?
- Am I saving or overspending?

Module 1 is local-first, single-user, and correctness-driven.  
It intentionally excludes automation, prediction, and advice.

---

## Goals

- Unified net worth across asset classes
- Clear asset allocation and concentration visibility
- Monthly portfolio trends
- Spending breakdown and savings rate
- File-based ingestion from financial sources
- Full traceability from source files to computed values

---

## Non-Goals

- Authentication
- AI features
- Real-time brokerage integrations
- Forecasting or alerts
- Financial recommendations
- Multi-user support

---

## User Experience

### Dashboard

The primary interface presents:

#### Net Worth

- Total net worth
- Breakdown by:
  - Cash
  - Stocks
  - Crypto
- Absolute values and percentages

---

#### Asset Allocation

Two dimensions:

1. Asset class
   - Cash
   - Stocks
   - Crypto

2. Geography
   - US
   - SG
   - India
   - Others

Displayed using pie charts and stacked bars.

---

#### Trends

- Net worth over time
- Portfolio value over time

Monthly granularity only.

---

#### Top Holdings

Displays top holdings across all asset classes combined.

Each entry includes:

- Asset name
- Asset class
- Percentage of total net worth

Optional toggle to view by asset class.

Purpose: highlight portfolio-wide concentration risk.

---

### Spending

Shows:

- Last month total spend
- Savings rate
- Top 3 spending categories
- Six-month spending trend

Categories support manual mapping.

---

### Data Ingestion

Single interface for importing:

1. IBKR portfolio reports (CSV)
2. Credit card statements
3. Coinbase exports
4. Blockchain balances (ETH + L2 via address)

Each source displays:

- Last import time
- Records processed
- Errors encountered

All raw inputs are retained for auditability.

---

## System Responsibilities

### Backend

- Parse uploaded files
- Normalize transactions and holdings
- Compute portfolio metrics
- Aggregate spending
- Generate monthly snapshots
- Expose dashboard APIs

All business logic resides in the backend.

---

### Frontend

- Render dashboards
- Display charts
- Manage file uploads
- Present ingestion status

Frontend contains no financial logic.

---

## Core Data Concepts

- Accounts
- Assets
- Holdings
- Transactions
- Raw imported files
- Ingestion jobs
- Monthly snapshots
- Locations

Design requirement:

Every computed number must be traceable to its source.

---

## Key Decisions

### Holdings

- Unified across all asset classes
- Expressed as percentage of total net worth
- Crypto treated as first-class assets

---

### Trends

- Monthly snapshots only
- No intraday tracking

---

### Spending

- Derived from bank and credit card imports
- Manual category overrides allowed

---

## Success Criteria

Module 1 is complete when the system can answer in under 30 seconds:

- What is my net worth?
- How is my capital allocated?
- Where is my largest concentration?
- How much cash do I have?
- Am I saving or overspending?

---

## Future Extensions

- Authentication
- Market intelligence ingestion
- Investment memo system
- Feedback loops
- AI-assisted analysis
