# Financial & Technical Glossary

This glossary defines domain-specific terms across Indian securities taxation, mutual fund accounting, and `folioman-client` architecture.

---

## Indian Personal Finance & Market Terminology

### AMC (Asset Management Company)
A registered entity (e.g. HDFC AMC, SBI Mutual Fund) that pools investor capital and manages investment portfolios according to stated scheme objectives under SEBI regulations.

### AMFI Code
A unique 6-digit numeric identifier assigned to every mutual fund scheme and variant (Direct/Regular, Growth/IDCW) by the **Association of Mutual Funds in India**. Used by `folioman-client` to fetch automated daily NAVs from AMFI bulk feeds and `mfapi.in`.

### Bhavcopy
The daily official trade summary file published at the close of trading by the National Stock Exchange of India (NSE) and Bombay Stock Exchange (BSE), containing closing, high, low, and open prices for all traded equities, ETFs, and bonds.

### CAS (Consolidated Account Statement)
A consolidated statement issued by Registrar and Transfer Agents (RTAs) such as **CAMS** and **KFintech**, listing all mutual fund holdings and transactions registered under an investor's Permanent Account Number (PAN).

### eCAS (Electronic Consolidated Account Statement)
A comprehensive depository statement issued by **NSDL** or **CDSL** combining depository equity holdings, demat mutual funds, ETFs, corporate bonds, and government securities under a single PAN.

### Folio Number
A unique account number assigned by an AMC to identify an investor's holding in their mutual fund schemes. Folioman normalizes folio numbers to reconcile differences across statements (e.g. stripping `/0` or space prefixes).

### ISIN (International Securities Identification Number)
A 12-character alphanumeric code that uniquely identifies a specific security (e.g. `INE002A01018` for Reliance Industries Limited). In India, ISINs start with the country prefix `IN`.

### NAV (Net Asset Value)
The per-unit market value of a mutual fund scheme, calculated by dividing the total net assets of the scheme by the total number of outstanding units at the close of every business day.

### XIRR (Extended Internal Rate of Return)
The annualized internal rate of return for a series of irregular, non-periodic cash inflows and outflows. `folioman-client` computes XIRR using a hybrid high-precision Newton-Raphson solver with a bisection fallback.

---

## Indian Tax Engine Terminology (Schedule 112A)

### Budget 2024 Cutoff (July 23, 2024)
The Finance (No. 2) Act, 2024 revised Indian capital gains tax rates effective July 23, 2024:
- **STCG (Section 111A)**: Increased from 15% to **20%**.
- **LTCG (Section 112A)**: Increased from 10% to **12.5%**.
- **LTCG Exemption Limit**: Increased from ₹1,00,000 to **₹1,25,000** per financial year.

### Section 112A Grandfathering
A statutory tax protection provision under Section 112A(4) of the Income Tax Act. For listed equity shares and equity mutual funds acquired on or before **January 31, 2018**, the cost basis is stepped up to the Fair Market Value (FMV) as of January 31, 2018, shielding gains accrued before that date from tax.

### Deemed Cost of Acquisition
The grandfathered cost basis computed under Section 112A:
$$\text{Deemed Cost} = \max(\text{Actual Purchase Cost}, \min(\text{FMV as of 31-Jan-2018}, \text{Full Value of Consideration}))$$

### Section 111A (STCG)
Tax levied on short-term capital gains arising from the sale of equity shares or units of an equity-oriented fund held for **12 months or less**, subject to STT.

### Section 50AA (Debt Mutual Funds)
Introduced in Finance Act 2023. Specifies that capital gains arising from the transfer of units of a "Specified Mutual Fund" (mutual funds where equity exposure is $\le 35\%$) acquired **on or after April 1, 2023** are deemed to be short-term capital gains, regardless of holding duration.

### Section 48 Expenses
Deductions permitted from full consideration:
- Expenditure incurred wholly and exclusively in connection with the transfer (brokerage, exchange turnover fees, clearing fees).
- Stamp duty incurred at acquisition.
- **Proviso**: Securities Transaction Tax (STT) is explicitly **disallowed** as a deduction.

### STT (Securities Transaction Tax)
A direct tax levied on every purchase and sale of securities listed on recognized Indian stock exchanges. Disallowed as a cost deduction under Section 48.

---

## Folioman Engine & Architecture Terminology

### Dedup Key (`dedup_key`)
A deterministic SHA-256 digest computed from core transaction attributes (`folio_id`, `security_id`, `date`, `units`, `amount`, `type`). Ensures idempotent imports when re-reading overlapping CAS statements.

### FIFO (First-In, First-Out)
Accounting method where the earliest acquired units in an asset position are the first to be consumed and matched against a disposal, ensuring strictly chronological cost basis allocation.

### Immutable Transaction Ledger
An invariant in `folioman-client`: rows in the `Transaction` table represent historical real-world financial events and are never mutated or rewritten to reflect corporate actions.

### Projected Ledger (`ProjectedLedger`)
A dynamic query layer that interleaves immutable historical transactions with declared corporate action events (splits, bonus issues), projecting on-the-fly adjusted unit quantities and effective prices.

### PAN Normalization & Dual Storage
Permanent Account Numbers (10-character Indian tax IDs) are normalized to uppercase, stripped of whitespace, and stored in two forms:
1. `pan_encrypted`: Fernet AES-128-CBC ciphertext.
2. `pan_hash`: Keyed HMAC-SHA256 digest used for deterministic SQL indexing.
Plaintext PANs are never written to database columns or log files.

### Partial Block (`PartialBlock`)
An anchor snapshot recorded when a CAS statement does not cover the complete lifetime history of a mutual fund scheme, creating a temporary cost-basis partition until earlier records are imported.
