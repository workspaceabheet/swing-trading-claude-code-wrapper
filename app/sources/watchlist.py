# Shared by app/sources/nse_bhavcopy.py and app/sources/screener_in.py.
# Per the user's confirmed decision, this slice does NOT scan the full NSE
# universe (~2000 symbols) -- it restricts Bhavcopy/Screener.in fetching to
# this fixed watchlist of liquid, large/mid-cap NSE symbols. Real stock-
# universe-selection logic belongs to the later Haiku sweep stage, not to
# sourcing.
WATCHLIST_TICKERS: list[str] = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "HINDUNILVR",
    "ITC",
    "SBIN",
    "BHARTIARTL",
    "KOTAKBANK",
    "LT",
    "AXISBANK",
    "BAJFINANCE",
    "MARUTI",
    "SUNPHARMA",
    "TITAN",
    "ULTRACEMCO",
    "ASIANPAINT",
    "WIPRO",
    "ADANIENT",
    "NTPC",
    "POWERGRID",
    # TATAMOTORS no longer exists on NSE: the company demerged into two
    # separately listed entities (commercial vehicles vs. passenger
    # vehicles). TMPV (Passenger Vehicles) is used here as the closer
    # match to the original retail-recognizable business; confirmed live
    # against both NSE Bhavcopy and Screener.in before this change.
    "TMPV",
    "TATASTEEL",
    "HCLTECH",
]
