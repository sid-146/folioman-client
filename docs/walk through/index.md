# System Flow & Ingestion Walkthrough

This section provides an exhaustive, end-to-end walkthrough of how `folioman-client` ingests, normalizes, stores, prices, and evaluates investment portfolios across all supported asset classes.

Whether processing mutual fund statements, demat equities, exchange-traded funds, fixed-income debentures, or cryptocurrencies, Folioman follows a unified architectural pipeline while applying specialized accounting rules tailored to each instrument.

---

## Architectural Pipeline Overview

```mermaid
flowchart TD
    subgraph Ingestion["1. Ingestion & Identity Resolution"]
        PDF["CAS / eCAS PDF"] --> Parser["Core Parsers (CAMS, KFintech, NSDL, CDSL)"]
        Parser --> Identity["Investor Resolution (HMAC-SHA256 & AES-GCM)"]
    end

    subgraph Normalization["2. Entity Normalization & Deduplication"]
        Identity --> Folio["Folio / Demat Account Normalization"]
        Identity --> Security["Security Resolution (AMFI, ISIN, Exchange Symbol)"]
        Security --> Dedup["SHA-256 Deduplication & Gap Detection"]
    end

    subgraph Storage["3. Dual-Model Storage Engine"]
        Dedup -->|Complete History| Ledger[("transactions (Ground Truth Ledger)")]
        Dedup -->|Incomplete MF History| Partials[("partial_blocks & holdings (Anchor Snapshot)")]
        Dedup -->|Demat Snapshot| Holdings[("holdings (Observed Snapshot)")]
    end

    subgraph Feeds["4. Multi-Source Pricing & Corporate Actions"]
        Ledger --> Pricing["Price Feeds (AMFI, Captnemo, Bhavcopy, Yahoo, CoinGecko)"]
        Holdings --> Pricing
        Pricing --> NAVHistory[("nav_history Table")]
        Pricing --> CA["Corporate Actions Replay (Splits, Bonus, Mergers)"]
    end

    subgraph Valuation["5. Valuation & Financial Math"]
        NAVHistory --> Engine["Valuation Engine & FIFO Lot Allocator"]
        CA --> Engine
        Engine --> Output["Portfolio Summary, XIRR, Allocations & Schedule 112A Tax"]
    end
```

---

## Dedicated Walkthrough Guides

Explore the detailed flow for each asset category:

<div class="grid cards" markdown>

-   :material-chart-pie: **[Mutual Funds Flow](mutual-funds.md)**
    
    ---
    
    Complete flow for CAMS and KFintech CAS PDFs: parser extraction, folio normalization, inception gap detection, dual-entry transaction ledger, partial block chaining, AMFI/mfapi pricing, FIFO lot matching, and Schedule 112A capital gains.

-   :material-finance: **[Stocks & Equities Flow](stocks.md)**
    
    ---
    
    Complete flow for NSDL and CDSL eCAS demat statements: depository extraction, ISIN-to-NSE/BSE symbol resolution via national reference catalogs, snapshot holding storage, corporate actions event replay (splits, bonuses, demergers), and NSE Bhavcopy pricing.

-   :material-gold: **[ETFs, Bonds & Other Assets Flow](etfs-and-others.md)**
    
    ---
    
    Complete flow for Exchange Traded Funds (ETFs), Sovereign Gold Bonds (SGBs), corporate debentures, Fixed Deposits (FDs), and Cryptocurrencies via CoinGecko, culminating in unified multi-asset portfolio rollups.

</div>

---

## Database Model Summary

Across all flows, Folioman organizes data into five relational groups in SQLite, PostgreSQL, or MySQL:

| Category | Primary Tables | Purpose |
| :--- | :--- | :--- |
| **Identity & Account** | `investors`, `families`, `amcs`, `folios` | Secure investor profile, encrypted PAN, multi-account structures. |
| **Securities & Reference** | `securities`, `ref_isins`, `ref_schemes`, `ref_meta` | Canonical master dictionary of schemes, equities, and metadata. |
| **Ledgers & Snapshots** | `transactions`, `holdings`, `partial_blocks` | Immutable trade transactions, observed statement snapshots, and chaining anchors. |
| **Market Data** | `nav_history`, `corporate_action_references`, `fx_rates` | Historical closing NAVs, equity prices, and SEBI corporate actions. |
| **Auditing & State** | `import_jobs`, `import_quarantines`, `security_integrity_statuses` | Import auditing, malformed block quarantining, and balance reconciliation. |
