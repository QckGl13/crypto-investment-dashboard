"""
collect_data.py

This script fetches cryptocurrency data from public APIs, computes technical
indicators and cycle metrics for a set of tracked coins, and writes the
resulting data to a JSON file. The output JSON serves as the source of
truth for the dashboard and downstream analysis routines.

Dependencies:
  - requests
  - pandas
  - pandas_ta
  - yfinance
  - beautifulsoup4 (not used here but installed for future scraping)
  - feedparser
  - jinja2 (used by send_email.py)

The script is intentionally self‑contained to run inside a GitHub Actions
workflow. Network calls are limited to the APIs specified in the project
requirements. If an API is unavailable or times out, the script will
raise an exception.
"""

import datetime
import json
from typing import Dict, List

import feedparser
import pandas as pd
import pandas_ta as ta
import requests
import yfinance as yf


# Mapping of CoinGecko identifiers to ticker symbols for use with yfinance
# Use USDT‑denominated tickers for better consistency with exchange pairs.
# If any of these symbols are not available on Yahoo Finance via yfinance,
# consider switching to a different data source or adjusting to a supported symbol.
COINS: Dict[str, str] = {
    "bitcoin": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "ripple": "XRPUSDT",
    "cardano": "ADAUSDT",
    "avalanche-2": "AVAXUSDT",
    "vechain": "VETUSDT",
    "vethor-token": "VTHOUSDT",
    # Terra classic/UST pair; using LUNAUSDT as requested.
    "terra-luna": "LUNAUSDT",
}

# YouTube channel IDs for the trusted analysts. These were derived from
# publicly available information. If any channel ID changes, update
# the corresponding value here. Each entry in this dictionary maps a
# friendly channel name to its YouTube channel identifier.
CHANNEL_IDS: Dict[str, str] = {
    "Benjamin Cowen": "UCRvqjQPSeaWn-uEx-w0XOIg",
    "Jason Pizzino": "UCIb34uXDsfTq4PJKW0eztkA",
    # Michael Pizzino shares a channel with Jason; we duplicate for completeness.
    "Michael Pizzino": "UCIb34uXDsfTq4PJKW0eztkA",
    "Crypto Capital Venture": "UCnMku7J_UtwlcSfZlIuQ3Kw",
}


def fetch_prices(coin_ids: List[str]) -> Dict[str, Dict[str, float]]:
    """Fetch current price and market data for a list of CoinGecko IDs.

    Returns a nested dictionary keyed by CoinGecko ID containing
    USD price, market cap and 24h change. Raises an exception if the
    request fails.
    """
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ",".join(coin_ids),
        "vs_currencies": "usd",
        "include_market_cap": "true",
        "include_24hr_change": "true",
        "include_last_updated_at": "true",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_global() -> (float, float):
    """Fetch global market metrics from CoinGecko.

    Returns the Bitcoin dominance (percentage of market cap) and total
    market capitalisation in USD.
    """
    url = "https://api.coingecko.com/api/v3/global"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()["data"]
    btc_dominance = float(data["market_cap_percentage"]["btc"])
    total_mcap = float(data["total_market_cap"]["usd"])
    return btc_dominance, total_mcap


def fetch_fear_greed() -> (int, str):
    """Fetch the current Fear & Greed index.

    The API returns a list of entries; we take the most recent value. If
    the API fails, an exception is raised.
    """
    url = "https://api.alternative.me/fng/"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()["data"][0]
    return int(data["value"]), data["value_classification"]


def fetch_youtube_videos(channel_id: str, days: int = 30, max_videos: int = 50) -> List[Dict[str, str]]:
    """Retrieve recent videos from a YouTube channel using its RSS feed.

    Args:
        channel_id: The YouTube channel identifier.
        days: Only videos published within this many days are retained.
        max_videos: Maximum number of videos to return.

    Returns:
        A list of dictionaries containing the title, link and ISO
        formatted publication timestamp for each video.
    """
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    feed = feedparser.parse(feed_url)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    videos: List[Dict[str, str]] = []
    for entry in feed.entries[:max_videos]:
        # published_parsed can be None if parsing fails; guard against it
        if not getattr(entry, "published_parsed", None):
            continue
        published = datetime.datetime(*entry.published_parsed[:6])
        if published < cutoff:
            continue
        videos.append({
            "title": entry.title,
            "link": entry.link,
            "published": published.isoformat(),
        })
    return videos


def compute_technicals(symbol: str) -> Dict[str, object]:
    """Compute technical indicators and cycle metrics for a given ticker symbol.

    This function downloads one year of daily price data via yfinance,
    calculates RSI, MACD histogram, Bollinger Band width and a set of
    Fibonacci retracement levels. It also computes a simple cycle score
    representing where the current price lies between the yearly low and
    high (0 = bottom, 1 = top).

    Args:
        symbol: A ticker symbol supported by yfinance (e.g. 'BTC-USD').

    Returns:
        A dictionary with the computed indicators. Missing values are
        converted to NaN and then cast to floats for JSON serialisation.
    """
    # Download last 365 days of daily OHLCV data
    df = yf.download(symbol, period="1y", interval="1d", progress=False)
    df = df.dropna()
    if df.empty or df.shape[0] < 30:
        raise ValueError(f"Insufficient data for symbol {symbol}")
    close = df["Close"]
    # RSI with 14‑day lookback
    rsi_series = ta.rsi(close, length=14)
    rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None
    # MACD histogram using default parameters (12,26,9)
    macd_df = ta.macd(close)
    macd_hist = float(macd_df["MACDh_12_26_9"].iloc[-1]) if not pd.isna(macd_df["MACDh_12_26_9"].iloc[-1]) else None
    # Bollinger Bands (20‑period, 2 std dev) and width as percentage of price
    bb = ta.bbands(close)
    upper = bb["BBU_20_2.0"].iloc[-1]
    lower = bb["BBL_20_2.0"].iloc[-1]
    bb_width = float((upper - lower) / close.iloc[-1]) if not pd.isna(upper) and not pd.isna(lower) else None
    # Yearly high/low and Fibonacci retracement levels
    high_price = float(close.max())
    low_price = float(close.min())
    fib_levels: Dict[str, float] = {}
    for ratio in [0.236, 0.382, 0.5, 0.618, 0.786]:
        level = high_price - (high_price - low_price) * ratio
        fib_levels[str(ratio)] = float(level)
    # Cycle score: 0.0 at yearly low, 1.0 at yearly high
    current_price = float(close.iloc[-1])
    cycle = 0.0
    if high_price > low_price:
        cycle = float((current_price - low_price) / (high_price - low_price))
    # Grab the last 90 closing prices and corresponding dates for charting.
    hist_series = close.tail(90)
    price_history = {
        "dates": [d.strftime("%Y-%m-%d") for d in hist_series.index],
        "prices": [float(p) for p in hist_series],
    }
    return {
        "rsi": rsi,
        "macd_hist": macd_hist,
        "bb_width": bb_width,
        "high": high_price,
        "low": low_price,
        "fibonacci": fib_levels,
        "cycle": cycle,
        "history": price_history,
    }


def derive_technical_risk(rsi: float) -> float:
    """Map RSI to a simple risk score between 0 and 1.

    RSI values above 70 are considered overbought (high risk), below 30
    oversold (low risk) and in between moderate. The returned value is
    linearly scaled within these regimes.
    """
    if rsi is None:
        return 0.5  # neutral if RSI is unavailable
    if rsi >= 70:
        return 1.0
    if rsi <= 30:
        return 0.0
    # Scale linearly between 30 and 70
    return (rsi - 30.0) / 40.0


def main() -> None:
    """Main entry point to orchestrate data collection and processing."""
    coin_ids = list(COINS.keys())
    prices = fetch_prices(coin_ids)
    btc_dominance, total_mcap = fetch_global()
    fng_value, fng_classification = fetch_fear_greed()
    # Fetch YouTube data for each channel
    videos: Dict[str, List[Dict[str, str]]] = {}
    for name, cid in CHANNEL_IDS.items():
        try:
            videos[name] = fetch_youtube_videos(cid)
        except Exception as e:
            # If an RSS feed fails, capture the error and continue
            videos[name] = []
    # Process each coin
    coin_data: Dict[str, Dict[str, object]] = {}
    cycle_values: List[float] = []
    for cg_id, symbol in COINS.items():
        # Price info may be missing if API is down; guard against KeyError
        price_info = prices.get(cg_id, {})
        price = price_info.get("usd")
        market_cap = price_info.get("usd_market_cap")
        change_24h = price_info.get("usd_24h_change")
        try:
            tech = compute_technicals(symbol)
            cycle_values.append(tech["cycle"])
            tech_risk = derive_technical_risk(tech["rsi"])
        except Exception:
            # Fallback if technical analysis fails
            tech = {}
            tech_risk = 0.5
            cycle_values.append(0.5)
        coin_data[symbol] = {
            "price": price,
            "market_cap": market_cap,
            "change_24h": change_24h,
            "technical": tech,
            "technical_risk": tech_risk,
            "cycle_score": tech.get("cycle"),
        }
    avg_cycle = float(sum(cycle_values) / len(cycle_values)) if cycle_values else 0.5
    # Assemble final data structure
    output = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "fear_greed_index": fng_value,
        "sentiment_classification": fng_classification,
        "btc_dominance": btc_dominance,
        "total_market_cap": total_mcap,
        "average_cycle": avg_cycle,
        "videos": videos,
        "coins": coin_data,
    }
    # Write to JSON for use by the dashboard and analysis engine
    with open("data.json", "w", encoding="utf-8") as outfile:
        json.dump(output, outfile, indent=2)


if __name__ == "__main__":
    main()
