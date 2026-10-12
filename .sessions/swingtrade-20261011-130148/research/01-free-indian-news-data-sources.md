# Research: Free Indian Stock News & Data Sources

## RSS/news feeds
Moneycontrol, Economic Times, Business Standard, Mint (LiveMint) all publish RSS feeds covering NSE/BSE company news, earnings, deals. Latency: minutes to hours; high reliability for major outlets. Specific feed URLs discoverable via the publishers' sites or aggregators like Feedspot.

## Official NSE/BSE machine-readable data
- **NSE Bhavcopy**: official daily EOD CSV (OHLC, volume, turnover) — free, public, no login, no stated rate limit. Available at nseindia.com Market Data → Reports, or mirrored via getbhavcopy.com.
- NSE corporate-announcements feed (filings page) updates within minutes of company filings — but official programmatic API access is costly (~₹3 lakh/year); third-party scrapers (Apify NSE/BSE Announcements, GitHub `nse-bse-api`, `BseIndiaApi`) bridge this gap in a legal gray zone.

## Google News RSS scraping
**Higher risk than other options** — Google's ToS prohibit automated scraping even though the RSS feed itself is public/machine-readable; triggers IP blocks. **Recommendation: avoid; use official publisher RSS feeds instead** (safer and equally useful).

## Free EOD price/volume/OHLC without Kite Connect
- NSE Bhavcopy / getbhavcopy.com (official, free, daily).
- `yfinance` — free, decent India coverage, slight lag.
- `NSEPython` — free wrapper for NSE public data (quotes, historical, live indices).
- `nsetools` — lightweight Bhavcopy parser.
No rate limits found on Bhavcopy; daily polling is safe.

## Free fundamentals
- **Screener.in** — fully free; P/E, market cap, balance sheet, quarterly results. Best fit for zero-budget.
- **Tickertape** — free tier has 200+ filters; paid tier only needed for exports.

## Global macro feeds
- **Trading Economics** (free) — economic calendar, 196-country indicators, API with JSON/CSV export, 24h updates. Best free macro-context source.
- Bloomberg/Reuters — no usable free tier.

## Recommended minimal daily-sweep stack (3-5 sources)
1. Moneycontrol RSS — company news/earnings.
2. NSE Bhavcopy — official EOD OHLC/volume.
3. Screener.in — fundamentals (P/E, market cap, results).
4. Trading Economics — macro counterweight context.
5. (optional) Economic Times/Mint RSS — news diversification.

Zero cost, no required signups, minimal legal risk (see [[06-legal-regulatory-caveats]]).

## Rate-limit / IP-ban risk at low frequency
- RSS feeds: 1-4x/day — very low risk.
- Bhavcopy: once/day (file only updates daily) — effectively zero risk.
- Screener.in scraping: once/day or every few days — moderate risk if aggressive; use randomized 2-5s delays, realistic user-agent, no concurrency, respect robots.txt crawl-delay.

Overall: once/day or a few times/day polling of the recommended stack is low-risk.
