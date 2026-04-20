#!/usr/bin/env python3
"""Live Net Worth Tracker - track assets, liabilities, and net worth with live prices."""

import json
import time
import argparse
import sys
from pathlib import Path
from datetime import datetime

import requests

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

PORTFOLIO_FILE = Path("portfolio.json")
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

console = Console() if RICH_AVAILABLE else None


# ---------------------------------------------------------------------------
# Portfolio I/O
# ---------------------------------------------------------------------------

def load_portfolio():
    if not PORTFOLIO_FILE.exists():
        print(f"No portfolio file found. Run with --init to create a sample one.")
        sys.exit(1)
    with open(PORTFOLIO_FILE) as f:
        return json.load(f)


def save_portfolio(portfolio):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2)


def init_portfolio():
    sample = {
        "assets": [
            {"name": "Checking Account", "type": "cash", "value": 10000},
            {"name": "Savings Account", "type": "cash", "value": 25000},
            {"name": "Apple Inc.", "type": "stock", "ticker": "AAPL", "shares": 10},
            {"name": "S&P 500 ETF", "type": "stock", "ticker": "SPY", "shares": 5},
            {"name": "Bitcoin", "type": "crypto", "coin_id": "bitcoin", "amount": 0.1},
            {"name": "Ethereum", "type": "crypto", "coin_id": "ethereum", "amount": 2.0},
            {"name": "Home Value", "type": "real_estate", "value": 450000},
        ],
        "liabilities": [
            {"name": "Mortgage", "type": "mortgage", "balance": 320000},
            {"name": "Car Loan", "type": "car_loan", "balance": 18000},
            {"name": "Credit Card", "type": "credit_card", "balance": 2500},
        ],
    }
    save_portfolio(sample)
    print(f"Created sample portfolio at {PORTFOLIO_FILE}")
    print("Edit it to match your actual assets and liabilities, then run:")
    print("  python net_worth_tracker.py")


# ---------------------------------------------------------------------------
# Live price fetching
# ---------------------------------------------------------------------------

def fetch_stock_prices(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    if not YFINANCE_AVAILABLE:
        print("Warning: yfinance not installed. Stock prices unavailable.")
        return {}
    prices = {}
    try:
        data = yf.download(tickers, period="1d", progress=False, auto_adjust=True)
        close = data["Close"] if len(tickers) > 1 else data["Close"]
        if len(tickers) == 1:
            last = close.dropna().iloc[-1] if not close.dropna().empty else None
            if last is not None:
                prices[tickers[0].upper()] = float(last)
        else:
            for ticker in tickers:
                col = close[ticker.upper()] if ticker.upper() in close.columns else None
                if col is not None:
                    last = col.dropna().iloc[-1] if not col.dropna().empty else None
                    if last is not None:
                        prices[ticker.upper()] = float(last)
    except Exception as e:
        print(f"Warning: could not fetch stock prices: {e}")
    return prices


def fetch_crypto_prices(coin_ids: list[str]) -> dict[str, float]:
    if not coin_ids:
        return {}
    try:
        resp = requests.get(
            COINGECKO_URL,
            params={"ids": ",".join(coin_ids), "vs_currencies": "usd"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {cid: data[cid]["usd"] for cid in coin_ids if cid in data}
    except Exception as e:
        print(f"Warning: could not fetch crypto prices: {e}")
        return {}


# ---------------------------------------------------------------------------
# Net worth calculation
# ---------------------------------------------------------------------------

def evaluate_portfolio(portfolio: dict) -> tuple[list[dict], list[dict], float, float]:
    assets = portfolio.get("assets", [])
    liabilities = portfolio.get("liabilities", [])

    stock_tickers = [a["ticker"] for a in assets if a["type"] == "stock"]
    coin_ids = [a["coin_id"] for a in assets if a["type"] == "crypto"]

    stock_prices = fetch_stock_prices(stock_tickers)
    crypto_prices = fetch_crypto_prices(coin_ids)

    evaluated_assets = []
    for a in assets:
        item = dict(a)
        if a["type"] == "stock":
            price = stock_prices.get(a["ticker"].upper())
            item["price"] = price
            item["current_value"] = price * a["shares"] if price else None
        elif a["type"] == "crypto":
            price = crypto_prices.get(a["coin_id"])
            item["price"] = price
            item["current_value"] = price * a["amount"] if price else None
        else:
            item["price"] = None
            item["current_value"] = a.get("value")
        evaluated_assets.append(item)

    total_assets = sum(
        i["current_value"] for i in evaluated_assets if i["current_value"] is not None
    )
    total_liabilities = sum(l["balance"] for l in liabilities)

    return evaluated_assets, liabilities, total_assets, total_liabilities


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def fmt_currency(value: float | None) -> str:
    if value is None:
        return "[dim]N/A[/dim]" if RICH_AVAILABLE else "N/A"
    formatted = f"${value:,.2f}"
    return formatted


def build_display(portfolio: dict) -> "Panel":
    evaluated_assets, liabilities, total_assets, total_liabilities = evaluate_portfolio(portfolio)
    net_worth = total_assets - total_liabilities
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Assets table
    asset_table = Table(title="Assets", box=box.SIMPLE_HEAVY, show_footer=True)
    asset_table.add_column("Name", style="cyan", footer="TOTAL")
    asset_table.add_column("Type", style="dim")
    asset_table.add_column("Details", style="dim")
    asset_table.add_column("Value", justify="right", footer=f"[bold green]{fmt_currency(total_assets)}[/bold green]")

    for a in evaluated_assets:
        details = ""
        if a["type"] == "stock":
            price_str = f"${a['price']:,.2f}" if a.get("price") else "N/A"
            details = f"{a['shares']} shares @ {price_str}"
        elif a["type"] == "crypto":
            price_str = f"${a['price']:,.2f}" if a.get("price") else "N/A"
            details = f"{a['amount']} @ {price_str}"
        elif a["type"] == "real_estate":
            details = "estimated"
        asset_table.add_row(
            a["name"],
            a["type"].replace("_", " "),
            details,
            fmt_currency(a["current_value"]),
        )

    # Liabilities table
    liab_table = Table(title="Liabilities", box=box.SIMPLE_HEAVY, show_footer=True)
    liab_table.add_column("Name", style="red", footer="TOTAL")
    liab_table.add_column("Type", style="dim")
    liab_table.add_column("Balance", justify="right", footer=f"[bold red]{fmt_currency(total_liabilities)}[/bold red]")

    for l in liabilities:
        liab_table.add_row(l["name"], l["type"].replace("_", " "), fmt_currency(l["balance"]))

    # Net worth summary
    color = "green" if net_worth >= 0 else "red"
    summary = Text()
    summary.append("\n  Total Assets:       ", style="dim")
    summary.append(fmt_currency(total_assets), style="green")
    summary.append("\n  Total Liabilities:  ", style="dim")
    summary.append(fmt_currency(total_liabilities), style="red")
    summary.append("\n  ─────────────────────────────\n", style="dim")
    summary.append(f"  Net Worth:          ", style="bold")
    summary.append(fmt_currency(net_worth), style=f"bold {color}")
    summary.append(f"\n\n  Updated: {timestamp}", style="dim")

    from rich.columns import Columns
    from rich.console import Group

    content = Group(asset_table, liab_table, Panel(summary, title="Summary", border_style=color))
    return Panel(content, title="[bold]Live Net Worth Tracker[/bold]", border_style="blue")


def print_plain(portfolio: dict):
    evaluated_assets, liabilities, total_assets, total_liabilities = evaluate_portfolio(portfolio)
    net_worth = total_assets - total_liabilities

    print("\n=== ASSETS ===")
    for a in evaluated_assets:
        val = f"${a['current_value']:,.2f}" if a["current_value"] is not None else "N/A"
        print(f"  {a['name']:30s} {val}")
    print(f"  {'TOTAL':30s} ${total_assets:,.2f}")

    print("\n=== LIABILITIES ===")
    for l in liabilities:
        print(f"  {l['name']:30s} ${l['balance']:,.2f}")
    print(f"  {'TOTAL':30s} ${total_liabilities:,.2f}")

    sign = "+" if net_worth >= 0 else ""
    print(f"\n  NET WORTH: {sign}${net_worth:,.2f}")
    print(f"  Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


# ---------------------------------------------------------------------------
# Portfolio editing helpers
# ---------------------------------------------------------------------------

def add_asset_interactive(portfolio: dict):
    print("\nAdd Asset")
    print("Types: cash, stock, crypto, real_estate, other")
    asset_type = input("Type: ").strip().lower()
    name = input("Name: ").strip()

    asset = {"name": name, "type": asset_type}
    if asset_type == "stock":
        asset["ticker"] = input("Ticker symbol (e.g. AAPL): ").strip().upper()
        asset["shares"] = float(input("Number of shares: ").strip())
    elif asset_type == "crypto":
        asset["coin_id"] = input("CoinGecko coin ID (e.g. bitcoin): ").strip().lower()
        asset["amount"] = float(input("Amount: ").strip())
    else:
        asset["value"] = float(input("Value ($): ").strip())

    portfolio["assets"].append(asset)
    save_portfolio(portfolio)
    print(f"Added asset: {name}")


def add_liability_interactive(portfolio: dict):
    print("\nAdd Liability")
    print("Types: mortgage, car_loan, credit_card, student_loan, other")
    liab_type = input("Type: ").strip().lower()
    name = input("Name: ").strip()
    balance = float(input("Balance ($): ").strip())

    portfolio["liabilities"].append({"name": name, "type": liab_type, "balance": balance})
    save_portfolio(portfolio)
    print(f"Added liability: {name}")


def list_items(portfolio: dict):
    print("\nAssets:")
    for i, a in enumerate(portfolio["assets"]):
        print(f"  [{i}] {a['name']} ({a['type']})")
    print("\nLiabilities:")
    for i, l in enumerate(portfolio["liabilities"]):
        print(f"  [{i}] {l['name']} (${l['balance']:,.2f})")


def remove_item(portfolio: dict, category: str, index: int):
    items = portfolio[category]
    if index < 0 or index >= len(items):
        print(f"Index {index} out of range.")
        return
    removed = items.pop(index)
    save_portfolio(portfolio)
    print(f"Removed: {removed['name']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Live Net Worth Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python net_worth_tracker.py           # Show current net worth
  python net_worth_tracker.py --watch   # Refresh every 30s (live mode)
  python net_worth_tracker.py --init    # Create a sample portfolio.json
  python net_worth_tracker.py --add-asset       # Add an asset
  python net_worth_tracker.py --add-liability   # Add a liability
  python net_worth_tracker.py --list            # List all items
  python net_worth_tracker.py --remove-asset 2  # Remove asset at index 2
        """,
    )
    parser.add_argument("--init", action="store_true", help="Create a sample portfolio.json")
    parser.add_argument("--watch", "-w", action="store_true", help="Live mode: refresh every N seconds")
    parser.add_argument("--interval", "-i", type=int, default=30, help="Refresh interval in seconds (default: 30)")
    parser.add_argument("--add-asset", action="store_true", help="Interactively add an asset")
    parser.add_argument("--add-liability", action="store_true", help="Interactively add a liability")
    parser.add_argument("--list", action="store_true", help="List all assets and liabilities")
    parser.add_argument("--remove-asset", type=int, metavar="INDEX", help="Remove asset by index")
    parser.add_argument("--remove-liability", type=int, metavar="INDEX", help="Remove liability by index")
    args = parser.parse_args()

    if args.init:
        init_portfolio()
        return

    portfolio = load_portfolio()

    if args.add_asset:
        add_asset_interactive(portfolio)
        return

    if args.add_liability:
        add_liability_interactive(portfolio)
        return

    if args.list:
        list_items(portfolio)
        return

    if args.remove_asset is not None:
        remove_item(portfolio, "assets", args.remove_asset)
        return

    if args.remove_liability is not None:
        remove_item(portfolio, "liabilities", args.remove_liability)
        return

    if args.watch and RICH_AVAILABLE:
        print(f"Live mode — refreshing every {args.interval}s. Press Ctrl+C to quit.\n")
        try:
            with Live(build_display(portfolio), refresh_per_second=1, screen=True) as live:
                while True:
                    time.sleep(args.interval)
                    live.update(build_display(portfolio))
        except KeyboardInterrupt:
            print("\nStopped.")
        return

    if RICH_AVAILABLE:
        console.print(build_display(portfolio))
    else:
        print_plain(portfolio)


if __name__ == "__main__":
    main()
