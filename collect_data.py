# collect_data.py
import os, json, time, requests
from datetime import datetime, timezone
from typing import Dict, Any, List
import pandas as pd
import yfinance as yf

CMC_KEY = os.getenv("COINMARKETCAP_API_KEY")
YT_KEY  = os.getenv("YOUTUBE_API_KEY")

# Mapea tus símbolos (usa los que estés graficando)
COINS = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "XRPUSDT": "XRP",
    "ADAUSDT": "ADA",
    "AVAXUSDT": "AVAX",
    "DOTUSDT":  "DOT",
    # agrega los que uses…
}

# YouTube channel IDs (ejemplo con tus 4 analistas)
YT_CHANNELS = {
    "Benjamin Cowen":   "UCljCQnkwqYqveXedDty75RA",
    "Jason Pizzino":    "UCnPKf9H6178m3u-4f1R9R3Q",
    "Michael Pizzino":  "UCtJb43uXDsfTp4PJXWbeztkA",
    "Crypto Capital Venture": "UCmKru73_UtwcLsFzIUQ3Kw",
}

def fetch_cmc_quotes(symbols: List[str]) -> Dict[str, Any]:
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_KEY}
    params = {"symbol": ",".join(symbols), "convert": "USD"}
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    data = r.json().get("data", {})
    out = {}
    for sym, payload in data.items():
        q = payload["quote"]["USD"]
        out[sym] = {
            "price": q["price"],
            "market_cap": q.get("market_cap"),
            "change_24h": q.get("percent_change_24h"),
            "last_updated": q.get("last_updated"),
        }
    return out

def fetch_youtube_latest(channel_id: String, max_results: int = 10) -> List[Dict[str, Any]]:
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YT_KEY, "channelId": channel_id, "part": "snippet",
        "order": "date", "maxResults": max_results, "type": "video"
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    return [
        {
            "videoId": it["id"]["videoId"],
            "title": it["snippet"]["title"],
            "publishedAt": it["snippet"]["publishedAt"]
        }
        for it in items
    ]

def three_bar_signal_yf(ticker: str, timeframe: str = "3D") -> str:
    # ticker: 'BTC-USD', 'ETH-USD', etc.
    hist = yf.Ticker(ticker).history(period="240d", interval="1d")
    if hist.empty:
        return "none"
    if timeframe.upper() == "3D":
        ohlc = hist.resample("3D").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
    elif timeframe.upper() == "1W":
        ohlc = hist.resample("1W").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
    else:
        ohlc = hist
    if len(ohlc) < 4:
        return "none"
    closes = ohlc["Close"].iloc[-4:-1]
    up   = all(closes[i] > closes[i-1] for i in range(1, len(closes)))
    down = all(closes[i] < closes[i-1] for i in range(1, len(closes)))
    return "bullish" if up else "bearish" if down else "none"

YF_TICKERS = {k: f"{v}-USD" for k, v in COINS.items()}

def build_three_bar_map() -> Dict[str, Dict[str, str]]:
    out = {}
    for sym, base in COINS.items():
        sig = three_bar_signal_yf(YF_TICKERS[sym], "3D")
        out[sym] = {"timeframe": "3D", "signal": sig}
        time.sleep(0.2)  # cortesía API Yahoo
    return out

def collect_youtube() -> Dict[str, Any]:
    out = {}
    for name, ch in YT_CHANNELS.items():
        try:
            out[name] = fetch_youtube_latest(ch, max_results=10)
            time.sleep(0.2)
        except Exception as e:
            out[name] = {"error": str(e), "items": []}
    return out

def main():
    # 1) Precios y métricas rápidas desde CMC
    cmc = fetch_cmc_quotes(list(COINS.values()))

    # 2) Señal 3-bar (yfinance)
    three_bar = build_three_bar_map()

    # 3) Últimos videos YouTube
    yt = collect_youtube()

    # 4) Sentimiento/ciclo: placeholders (puedes sustituir por tus fuentes)
    sentiment = {"classification": "neutral", "fear_greed_index": 50}
    cycle = {"average_cycle": 0.5}

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coins": list(COINS.keys()),
        "cmc": cmc,
        "three_bar": three_bar,
        "youtube": yt,
        "sentiment": sentiment,
        "cycle": cycle,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
