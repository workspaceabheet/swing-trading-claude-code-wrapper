# Research: Zerodha Kite Without API Access

## Manual export
Holdings, trade book, and funds statement can be manually exported as CSV/XLSX from Kite Console. Point-in-time only, no streaming/real-time data.

## Unofficial scraping libraries & ToS risk
Unofficial libraries exist (session-cookie or Selenium based) that replicate Kite API without paying ~₹2000/month. **Zerodha's ToS (Section 16.3) explicitly forbids** extracting/scraping/harvesting market data from Kite Web/Mobile except through the official paid API, and prohibits reverse-engineering/undocumented API calls. Consequence: account suspension/termination. Risk is described as high and unambiguous (not a gray area) — Zerodha actively monitors for this (login pattern/request-rate/session anomalies).

**Verdict: not defensible, even for personal use only** — the ToS violation isn't excused by non-commercial intent.

## Cheaper/free alternative broker APIs
- **Upstox API** — free, no subscription, real-time data + holdings/positions/orders/P&L, official SDKs. Recommended alternative.
- **Angel One SmartAPI** — free, 10 orders/sec rate limit.
- **Fyers API** — free but order placement disabled from April 1, 2026 (data-only after that).
- **Dhan** — free API access.

All three carry zero ToS risk (official, regulation-compliant channels).

## Gaps if Kite is dropped entirely for v1
For a once-daily, advisory-only (non-execution) tool:
- Historical OHLC: no gap (yfinance, NSE bhavcopy).
- Holdings/P&L: no gap (manual CSV export, or Upstox API).
- Real-time prices: minor gap if using only EOD bhavcopy/yfinance; solved if Upstox API is added.
- Live intraday ticks: gap, but not needed for a once-daily advisory tool.

## Recommendation
**Drop Kite entirely for v1.** Optionally add the free Upstox API later for live reference prices/holdings. Use yfinance/NSE bhavcopy for historical OHLC. If portfolio context is wanted without any API, a manual CSV export from Kite can be used as a one-off, non-automated input — never automated scraping.

Sources: zerodha.com/terms-and-conditions, kite.trade/terms, upstox.com/trading-api, Fyers API support docs.
