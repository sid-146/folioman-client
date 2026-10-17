# Simple Ideas & Everyday Use-Cases for folioman-client

`folioman-client` is a zero-configuration, embedded financial engine for Indian personal finance, mutual funds, and equities. Because it requires **no remote servers, no background daemons, and no database setup** (using an embedded SQLite database by default), it is ideal for building quick scripts, automation bots, interactive dashboards, and developer weekend projects.

While [`USE_CASES.md`](file:///d:/GitHub_Clones/folioman-client/USE_CASES.md) covers complex enterprise and RIA workflows, this document focuses on **10 simple, practical, and fun ideas you can build in an afternoon or weekend**.

---

## Table of Ideas

1. [Telegram / Discord Daily Net Worth Bot](#1-telegram-discord-daily-net-worth-bot)
2. [Interactive Streamlit Portfolio Dashboard (Web UI)](#2-interactive-streamlit-portfolio-dashboard-web-ui)
3. [Tax-Loss Harvesting & ₹1.25L LTCG Exemption Alert](#3-tax-loss-harvesting-125l-ltcg-exemption-alert)
4. ["Active Funds vs. Nifty 50" SIP Benchmark Comparator](#4-active-funds-vs-nifty-50-sip-benchmark-comparator)
5. [Rich Terminal Portfolio TUI (Hacker Dashboard)](#5-rich-terminal-portfolio-tui-hacker-dashboard)
6. [Automated Email Statement Ingestion Watcher](#6-automated-email-statement-ingestion-watcher)
7. [Mutual Fund NAV Dip & Lumpsum Buying Notifier](#7-mutual-fund-nav-dip-lumpsum-buying-notifier)
8. [Target Asset Allocation & Rebalancing Calculator](#8-target-asset-allocation-rebalancing-calculator)
9. [Excel / Google Sheets Live Sync Script](#9-excel-google-sheets-live-sync-script)
10. [Local Micro-API for Apple Shortcuts / Home Assistant / Notion](#10-local-micro-api-for-apple-shortcuts-home-assistant-notion)

---

## 1. Telegram / Discord Daily Net Worth Bot

### Why Build This?
Mutual fund NAVs are published every evening between 9:00 PM and 11:00 PM IST by AMFI. Instead of logging into multiple broker apps (Zerodha, Groww, Kuvera), run a script every night on a Raspberry Pi or cron job that pings your private Telegram or Discord channel with your updated net worth and day's profit/loss.

### Key `folioman-client` Features
- `client.navs.refresh()`: Automatically syncs the latest closing NAVs from AMFI.
- `client.portfolio.get()`: Returns total net worth, day change (INR), and day change (%).

### Complete Code Blueprint

```python
import asyncio
import os
import httpx
from folioman_client import FoliomanClient

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")


async def send_telegram_alert(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as http:
        await http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})


async def daily_net_worth_update() -> None:
    async with FoliomanClient() as client:
        # 1. Sync latest daily prices
        print("Fetching latest NAVs...")
        await client.navs.refresh()

        # 2. Get today's summary
        summary = await client.portfolio.get(investor_id=1)
        holdings = await client.holdings.list(investor_id=1)

        # 3. Format message
        day_arrow = "🟢 +" if summary.day_change_inr and summary.day_change_inr >= 0 else "🔴 "
        day_chg_str = (
            f"{day_arrow}₹{abs(summary.day_change_inr):,.2f} ({summary.day_change_pct:+.2%})"
            if summary.day_change_inr is not None
            else "N/A"
        )
        xirr_str = f"{summary.xirr * 100:.2f}%" if summary.xirr else "N/A"

        # Top 3 holdings by valuation
        top_holdings = "\n".join(
            f"• {h.name[:25]}...: ₹{h.value_inr:,.0f} ({h.day_change_pct:+.2%})"
            for h in sorted(holdings, key=lambda x: x.value_inr or 0, reverse=True)[:3]
        )

        msg = (
            f"📊 *Daily Portfolio Briefing*\n\n"
            f"💰 *Net Worth:* ₹{summary.total_inr:,.2f}\n"
            f"📈 *Today's Change:* {day_chg_str}\n"
            f"🚀 *All-time XIRR:* {xirr_str}\n\n"
            f"🏆 *Top Holdings:*\n{top_holdings}"
        )

        await send_telegram_alert(msg)
        print("Alert sent successfully!")


if __name__ == "__main__":
    asyncio.run(daily_net_worth_update())
```

---

## 2. Interactive Streamlit Portfolio Dashboard (Web UI)

### Why Build This?
You want a private, clean web dashboard to visualize your wealth without uploading sensitive financial statements to commercial cloud platforms. You drop in your CAS PDF, enter your PAN password, and instantly see pie charts of your asset allocation, AMC exposure, and holdings.

### Key `folioman-client` Features
- `client.imports.cas_pdf()`: Ingests statements on the fly.
- `summary.asset_mix` & `summary.amc_mix`: Pre-computed portfolio categorization.
- `client.holdings.list()`: Detailed table of priced positions.

### Complete Code Blueprint (`app.py`)

```python
import asyncio
import tempfile
import streamlit as st
import pandas as pd
import plotly.express as px
from folioman_client import FoliomanClient

st.set_page_config(page_title="My Private Portfolio", layout="wide", page_icon="📈")
st.title("🛡️ Private Portfolio Dashboard")


async def run_import_and_fetch(pdf_bytes: bytes, password: str):
    async with FoliomanClient() as client:
        # Save temporary file for CAS parser
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        await client.imports.cas_pdf(file_path=tmp_path, password=password)
        await client.navs.refresh()
        summary = await client.portfolio.get(investor_id=1)
        holdings = await client.holdings.list(investor_id=1)
        return summary, holdings


# Sidebar upload
st.sidebar.header("Statement Ingestion")
uploaded_file = st.sidebar.file_uploader("Upload CAMS/KFintech CAS PDF", type=["pdf"])
pan_pass = st.sidebar.text_input("CAS PDF Password (PAN)", type="password")

if uploaded_file and pan_pass:
    if st.sidebar.button("Process Statement"):
        with st.spinner("Parsing statement & fetching market prices..."):
            summary, holdings = asyncio.run(run_import_and_fetch(uploaded_file.read(), pan_pass))
            st.session_state["summary"] = summary
            st.session_state["holdings"] = holdings
            st.success("Portfolio successfully updated!")

if "summary" in st.session_state:
    summary = st.session_state["summary"]
    holdings = st.session_state["holdings"]

    # Top KPI Metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Net Worth", f"₹{summary.total_inr:,.2f}")
    col2.metric("Portfolio XIRR", f"{summary.xirr * 100:.2f}%" if summary.xirr else "N/A")
    day_pct = f"{summary.day_change_pct * 100:.2f}%" if summary.day_change_pct else "0.0%"
    col3.metric("Day Change", f"₹{summary.day_change_inr:,.2f}" if summary.day_change_inr else "₹0.00", day_pct)

    # Charts Row
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Asset Allocation")
        mix_data = [{"Asset": m.security_type, "Value": float(m.value_inr)} for m in summary.asset_mix]
        fig_asset = px.pie(pd.DataFrame(mix_data), names="Asset", values="Value", hole=0.4)
        st.plotly_chart(fig_asset, use_container_width=True)

    with c2:
        st.subheader("Fund House (AMC) Concentration")
        amc_data = [{"AMC": m.label, "Value": float(m.value_inr)} for m in summary.amc_mix]
        fig_amc = px.bar(pd.DataFrame(amc_data), x="Value", y="AMC", orientation="h")
        st.plotly_chart(fig_amc, use_container_width=True)

    # Holdings Table
    st.subheader("Holdings Breakdown")
    table_data = [
        {
            "Scheme / Stock": h.name,
            "Units": f"{h.units:,.3f}",
            "Current NAV": f"₹{h.nav_or_price:,.2f}" if h.nav_or_price else "N/A",
            "Current Value": f"₹{h.value_inr:,.2f}" if h.value_inr else "N/A",
            "1-Day Move": f"{h.day_change_pct:+.2%}" if h.day_change_pct else "0.0%",
        }
        for h in holdings
    ]
    st.dataframe(pd.DataFrame(table_data), use_container_width=True)
else:
    st.info("Upload your CAS statement in the sidebar to get started.")
```

Run via:
```bash
streamlit run app.py
```

---

## 3. Tax-Loss Harvesting & ₹1.25L LTCG Exemption Alert

### Why Build This?
Under Section 112A of the Indian Income Tax Act (post-Budget 2024), **the first ₹1,25,000 of Long-Term Capital Gains (LTCG) in equity mutual funds and stocks is completely tax-free every financial year**. 

If you don't realize this ₹1.25L gain before March 31, the exemption resets and is wasted. This script scans your portfolio to identify:
1. How much LTCG you have already realized this year.
2. How much tax-free allowance you have remaining.
3. Which long-term holdings can be redeemed and re-invested to legally save tax.

### Complete Code Blueprint

```python
import asyncio
from decimal import Decimal
from folioman_client import FoliomanClient

EXEMPTION_LIMIT_INR = Decimal("125000.00")  # ₹1.25 Lakh annual tax-free LTCG exemption


async def tax_harvesting_advisor(investor_id: int = 1, current_fy: str = "2024-25") -> None:
    async with FoliomanClient() as client:
        # 1. Fetch already realized capital gains for the fiscal year
        gains = await client.capital_gains.get(investor_id=investor_id, fy=current_fy)
        already_realized_ltcg = gains.ltcg_total or Decimal("0")

        remaining_exemption = max(Decimal("0"), EXEMPTION_LIMIT_INR - already_realized_ltcg)

        print(f"=== Tax Harvesting Advisor (FY {current_fy}) ===")
        print(f"Annual Section 112A Exemption: ₹{EXEMPTION_LIMIT_INR:,.2f}")
        print(f"LTCG Realized So Far:          ₹{already_realized_ltcg:,.2f}")
        print(f"Remaining Tax-Free Headroom:   ₹{remaining_exemption:,.2f}\n")

        if remaining_exemption <= 0:
            print("✅ You have already fully utilized your ₹1.25L tax-free LTCG quota for this FY!")
            return

        # 2. Inspect holdings to suggest tax harvesting candidates
        holdings = await client.holdings.list(investor_id=investor_id)
        print("💡 Potential Holdings to Harvest (Sell & Re-buy to step up cost basis):")

        for h in holdings:
            if h.security_type != "MF" or not h.value_inr:
                continue
            # Highlight holdings with positive unrealized value
            print(f"• {h.name}: Current Value ₹{h.value_inr:,.2f} ({h.units:,.3f} units)")

        print(f"\nTip: Redeem up to ₹{remaining_exemption:,.2f} of gains before March 31 to lock in 0% tax.")


if __name__ == "__main__":
    asyncio.run(tax_harvesting_advisor())
```

---

## 4. "Active Funds vs. Nifty 50" SIP Benchmark Comparator

### Why Build This?
Investors often pay 0.5%–1.5% expense ratios for actively managed mutual funds. But did those funds actually beat a plain Nifty 50 index fund? 

This script takes the exact transaction cashflows from your statement, computes your actual personal portfolio XIRR, and compares your returns with market benchmarks.

### Complete Code Blueprint

```python
import asyncio
from folioman_client import FoliomanClient
from folioman_client.core.xirr import xirr


async def benchmark_comparison(investor_id: int = 1) -> None:
    async with FoliomanClient() as client:
        summary = await client.portfolio.get(investor_id=investor_id)
        transactions = await client.transactions.list(investor_id=investor_id)

        print("=== Portfolio Benchmark Analysis ===")
        actual_xirr = summary.xirr * 100 if summary.xirr else 0.0
        print(f"Your Portfolio Total Value: ₹{summary.total_inr:,.2f}")
        print(f"Your Actual Portfolio XIRR:  {actual_xirr:.2f}%\n")

        # Extract all net cash flow events (outflows as negative, current value as positive)
        cash_flows = []
        for tx in transactions:
            amt = float(tx.amount)
            # Inflows to portfolio (buys/SIPs) are cash outflows from investor wallet
            flow = -amt if tx.transaction_type in ("BUY", "SIP", "PURCHASE") else amt
            cash_flows.append((tx.date, flow))

        print(f"Analyzed {len(cash_flows)} historical transactions across your lifetime portfolio.")
        print("Benchmark Comparison:")
        print(f"• Actual Portfolio XIRR:      {actual_xirr:.2f}%")
        print("• Nifty 50 Index 10-Yr CAGR:  ~13.20%")
        print("• Nifty Next 50 10-Yr CAGR:   ~16.40%")

        diff = actual_xirr - 13.20
        if diff >= 0:
            print(f"\n🎉 Great job! Your portfolio generated +{diff:.2f}% alpha over the Nifty 50 index.")
        else:
            print(f"\n⚠️ Your portfolio lagged the Nifty 50 index by {abs(diff):.2f}%. Consider low-cost index funds.")


if __name__ == "__main__":
    asyncio.run(benchmark_comparison())
```

---

## 5. Rich Terminal Portfolio TUI (Hacker Dashboard)

### Why Build This?
If you live in the command line, you don't need a heavy browser window just to check your stocks and mutual funds. Using Python's `rich` library and `folioman-client`, you can render a fast, colorful ASCII terminal dashboard in 30 lines.

### Complete Code Blueprint (`cli_dashboard.py`)

```python
import asyncio
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from folioman_client import FoliomanClient

console = Console()


async def render_terminal_dashboard():
    async with FoliomanClient() as client:
        summary = await client.portfolio.get(investor_id=1)
        holdings = await client.holdings.list(investor_id=1)

        # Header panel
        day_color = "green" if summary.day_change_inr and summary.day_change_inr >= 0 else "red"
        day_str = (
            f"[{day_color}]₹{summary.day_change_inr:,.2f} ({summary.day_change_pct:+.2%})[/{day_color}]"
            if summary.day_change_inr
            else "N/A"
        )
        xirr_val = f"[cyan]{summary.xirr * 100:.2f}%[/cyan]" if summary.xirr else "N/A"

        header_text = (
            f"[b]Total Net Worth:[/b] [bold green]₹{summary.total_inr:,.2f}[/bold green]  │  "
            f"[b]Day Change:[/b] {day_str}  │  "
            f"[b]Portfolio XIRR:[/b] {xirr_val}"
        )
        console.print(Panel(header_text, title="💼 Folioman Portfolio Monitor", expand=False))

        # Holdings Table
        table = Table(title="Priced Holdings", show_header=True, header_style="bold magenta")
        table.add_column("Security Name", style="white", max_width=40, no_wrap=True)
        table.add_column("Type", justify="center", style="dim")
        table.add_column("Units", justify="right")
        table.add_column("Current NAV / Price", justify="right")
        table.add_column("Value (INR)", justify="right", style="bold")
        table.add_column("1D Move", justify="right")

        for h in sorted(holdings, key=lambda x: x.value_inr or 0, reverse=True):
            move_color = "green" if h.day_change_pct and h.day_change_pct >= 0 else "red"
            move_str = f"[{move_color}]{h.day_change_pct:+.2%}[/{move_color}]" if h.day_change_pct else "0.00%"
            table.add_row(
                h.name,
                h.security_type,
                f"{h.units:,.3f}",
                f"₹{h.nav_or_price:,.2f}" if h.nav_or_price else "—",
                f"₹{h.value_inr:,.2f}" if h.value_inr else "—",
                move_str,
            )

        console.print(table)


if __name__ == "__main__":
    asyncio.run(render_terminal_dashboard())
```

---

## 6. Automated Email Statement Ingestion Watcher

### Why Build This?
Every month, CAMS and KFintech automatically email your updated Consolidated Account Statement (CAS). Instead of downloading the attachment, finding the file, and running manual CLI commands, a small Python script can poll your inbox (via IMAP), detect the CAS email, extract the PDF attachment, and import it into `folioman-client` automatically!

### Complete Code Blueprint

```python
import imaplib
import email
from email.header import decode_header
import asyncio
import os
from folioman_client import FoliomanClient

IMAP_SERVER = "imap.gmail.com"
EMAIL_USER = os.getenv("EMAIL_USER", "you@gmail.com")
EMAIL_PASS = os.getenv("EMAIL_APP_PASSWORD", "app_specific_password")
PAN_PASSWORD = os.getenv("INVESTOR_PAN", "ABCDE1234F")


async def ingest_cas_attachment(pdf_path: str) -> None:
    async with FoliomanClient() as client:
        print(f"Ingesting new statement: {pdf_path}")
        job = await client.imports.cas_pdf(file_path=pdf_path, password=PAN_PASSWORD)
        print("Import completed! Re-indexing NAVs...")
        await client.navs.refresh()
        print("Portfolio up to date!")


def check_email_for_cas():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    # Search for unread emails from CAMS or KFintech
    status, messages = mail.search(None, '(UNSEEN SUBJECT "Consolidated Account Statement")')
    if status != "OK" or not messages[0]:
        print("No new CAS statements found.")
        return

    for num in messages[0].split():
        _, msg_data = mail.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                filename = part.get_filename()
                if filename and filename.endswith(".pdf"):
                    filepath = os.path.join("./statements", filename)
                    os.makedirs("./statements", exist_ok=True)
                    with open(filepath, "wb") as f:
                        f.write(part.get_payload(decode=True))
                    print(f"Downloaded statement to {filepath}")
                    asyncio.run(ingest_cas_attachment(filepath))

    mail.close()
    mail.logout()


if __name__ == "__main__":
    check_email_for_cas()
```

---

## 7. Mutual Fund NAV Dip & Lumpsum Buying Notifier

### Why Build This?
Many investors like "buying the dip"—investing extra cash when the market drops by 1.5% or 2% in a single trading session. This script monitors your core index funds and pings you whenever an NAV drops significantly.

### Complete Code Blueprint

```python
import asyncio
from folioman_client import FoliomanClient

DIP_THRESHOLD_PERCENT = -1.50  # Alert if NAV fell more than 1.5% in a day


async def check_for_dips():
    async with FoliomanClient() as client:
        print("Checking today's NAV changes...")
        await client.navs.refresh()
        holdings = await client.holdings.list(investor_id=1)

        dips_detected = []
        for h in holdings:
            if h.day_change_pct is not None and (h.day_change_pct * 100) <= DIP_THRESHOLD_PERCENT:
                dips_detected.append(h)

        if dips_detected:
            print("\n🚨 Market Dip Alert! The following funds are on sale:")
            for d in dips_detected:
                pct = d.day_change_pct * 100
                print(f"📉 {d.name}")
                print(f"   Change: {pct:.2f}% | Current NAV: ₹{d.nav_or_price:,.2f}")
                print(f"   Action: Consider a lumpsum top-up!\n")
        else:
            print("No major dips today. Markets were stable or green.")


if __name__ == "__main__":
    asyncio.run(check_for_dips())
```

---

## 8. Target Asset Allocation & Rebalancing Calculator

### Why Build This?
If your goal is a 70% Equity / 20% Debt / 10% Gold allocation, market movements will cause your portfolio to drift over time. This tool computes your current allocation and tells you the exact rupee amounts to buy or sell to restore balance.

### Complete Code Blueprint

```python
import asyncio
from decimal import Decimal
from folioman_client import FoliomanClient

# Desired Target Allocation
TARGET_ALLOCATION = {
    "EQUITY": Decimal("0.70"),  # 70%
    "DEBT": Decimal("0.20"),    # 20%
    "GOLD": Decimal("0.10"),    # 10%
}


async def calculate_rebalance(investor_id: int = 1):
    async with FoliomanClient() as client:
        summary = await client.portfolio.get(investor_id=investor_id)
        total_val = summary.total_inr

        if not total_val or total_val == 0:
            print("Portfolio has zero balance.")
            return

        # Map existing asset mix
        current_alloc = {mix.security_type.upper(): mix.value_inr for mix in summary.asset_mix}

        print(f"=== Portfolio Rebalance Report (Total: ₹{total_val:,.2f}) ===")
        print(f"{'Asset Class':<12} {'Current':>14} {'Target':>14} {'Diff (INR)':>16} {'Action':<10}")
        print("-" * 70)

        for asset, target_pct in TARGET_ALLOCATION.items():
            curr_val = current_alloc.get(asset, Decimal("0"))
            target_val = total_val * target_pct
            diff_val = target_val - curr_val

            action = f"BUY  ₹{diff_val:,.2f}" if diff_val > 0 else f"SELL ₹{abs(diff_val):,.2f}"
            print(f"{asset:<12} ₹{curr_val:>12,.2f} ₹{target_val:>12,.2f} ₹{diff_val:>14,.2f} {action:<10}")


if __name__ == "__main__":
    asyncio.run(calculate_rebalance())
```

---

## 9. Excel / Google Sheets Live Sync Script

### Why Build This?
Many investors and Chartered Accountants love Microsoft Excel or Google Sheets for custom modeling, retirement planning, and tax returns. This script automatically exports your entire holdings, transaction ledger, and tax lots to an Excel workbook (`portfolio.xlsx`) with formatted headers.

### Complete Code Blueprint

```python
import asyncio
import pandas as pd
from folioman_client import FoliomanClient


async def export_to_excel(filename: str = "my_portfolio.xlsx") -> None:
    async with FoliomanClient() as client:
        holdings = await client.holdings.list(investor_id=1)
        transactions = await client.transactions.list(investor_id=1)
        gains = await client.capital_gains.get(investor_id=1, fy="2024-25")

        # 1. Holdings DataFrame
        df_holdings = pd.DataFrame([
            {
                "Security Name": h.name,
                "Type": h.security_type,
                "Units": float(h.units),
                "NAV / Price": float(h.nav_or_price) if h.nav_or_price else 0.0,
                "Current Value (INR)": float(h.value_inr) if h.value_inr else 0.0,
                "1-Day Change (%)": float(h.day_change_pct * 100) if h.day_change_pct else 0.0,
            }
            for h in holdings
        ])

        # 2. Transactions DataFrame
        df_tx = pd.DataFrame([
            {
                "Date": tx.date,
                "Security ID": tx.security_id,
                "Type": tx.transaction_type,
                "Units": float(tx.units),
                "Price": float(tx.nav_or_price),
                "Amount": float(tx.amount),
            }
            for tx in transactions
        ])

        # 3. Capital Gains (Schedule 112A)
        df_gains = pd.DataFrame([
            {
                "Security": r.security_name,
                "Sell Date": r.sell_date,
                "Units": float(r.units),
                "Sell Price": float(r.sell_price),
                "Cost Basis": float(r.cost_basis),
                "Gain (INR)": float(r.gain_inr),
                "Gain Type": r.gain_type,
            }
            for r in gains.rows
        ])

        # Write all sheets
        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            df_holdings.to_excel(writer, sheet_name="Holdings", index=False)
            df_tx.to_excel(writer, sheet_name="Ledger", index=False)
            df_gains.to_excel(writer, sheet_name="Schedule_112A", index=False)

        print(f"🎉 Successfully exported portfolio data to {filename}!")


if __name__ == "__main__":
    asyncio.run(export_to_excel())
```

---

## 10. Local Micro-API for Apple Shortcuts / Home Assistant / Notion

### Why Build This?
You want to see your portfolio net worth in your **Apple Watch complication**, an **iPhone lock screen widget** (via Apple Shortcuts), or your **Home Assistant smart home tablet display**. With FastAPI and `folioman-client`, you can expose your portfolio data as a secure, local REST API in under 40 lines of code.

### Complete Code Blueprint (`server.py`)

```python
from fastapi import FastAPI, HTTPException
from folioman_client import FoliomanClient
import uvicorn

app = FastAPI(title="Local Portfolio Micro-API", description="Personal net worth endpoint")


@app.get("/api/v1/net-worth")
async def get_net_worth(investor_id: int = 1):
    async with FoliomanClient() as client:
        summary = await client.portfolio.get(investor_id=investor_id)
        if not summary:
            raise HTTPException(status_code=404, detail="Investor not found")

        return {
            "total_net_worth_inr": float(summary.total_inr),
            "xirr_percent": float(summary.xirr * 100) if summary.xirr else None,
            "day_change_inr": float(summary.day_change_inr) if summary.day_change_inr else 0.0,
            "day_change_percent": float(summary.day_change_pct * 100) if summary.day_change_pct else 0.0,
        }


@app.post("/api/v1/refresh-prices")
async def refresh_prices():
    async with FoliomanClient() as client:
        stats = await client.navs.refresh()
        return {"status": "ok", "updated_points": stats}


if __name__ == "__main__":
    # Runs on localhost port 8000
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
```

Now you can test it directly:
```bash
curl http://127.0.0.1:8000/api/v1/net-worth
```
Response:
```json
{
  "total_net_worth_inr": 1845200.5,
  "xirr_percent": 15.42,
  "day_change_inr": 12400.0,
  "day_change_percent": 0.68
}
```

---

## Summary Comparison: What Fits Your Need?

| Project Idea | Complexity | Time to Build | Primary Output |
| :--- | :---: | :---: | :--- |
| **Telegram / Discord Bot** | Low | ~30 mins | Automated evening chat notification |
| **Streamlit Web Dashboard** | Low | ~45 mins | Interactive browser charts & tables |
| **Tax-Loss Harvesting Alert** | Low | ~20 mins | Terminal advice before March 31 |
| **SIP vs Nifty Benchmark** | Low | ~25 mins | Alpha comparison vs Nifty 50 index |
| **Rich Terminal TUI** | Low | ~20 mins | Hacker-friendly command line display |
| **Email Watcher Script** | Medium | ~1 hour | Fully automated background statement sync |
| **NAV Dip Notifier** | Low | ~20 mins | Push notification to buy market drops |
| **Asset Rebalancer** | Low | ~25 mins | Rupee buy/sell rebalancing targets |
| **Excel Export Sync** | Low | ~20 mins | Formatted `.xlsx` spreadsheet for your CA |
| **FastAPI Micro-API** | Low | ~30 mins | JSON feed for Apple Shortcuts & Smart Home |

All of these ideas leverage the same embedded engine: **no external cloud subscriptions, no database servers to manage, and complete data privacy**.
