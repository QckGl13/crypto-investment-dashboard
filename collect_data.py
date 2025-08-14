# collect_data.py
import os, json, time, requests
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
import pandas as pd
import pandas_ta as ta
import yfinance as yf

CMC_KEY = os.getenv("COINMARKETCAP_API_KEY")
YT_KEY  = os.getenv("YOUTUBE_API_KEY")

# === Config: símbolos y canales ===
COINS = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "XRPUSDT": "XRP",
    "ADAUSDT": "ADA",
    "AVAXUSDT": "AVAX",
    "DOTUSDT":  "DOT",
    "LUNAUSDT": "LUNA",
}
YF_TICKERS = {k: f"{v}-USD" for k, v in COINS.items()}
YT_CHANNELS = {
    "Benjamin Cowen": "UCRvqjQPSeaWn-uEx-w0XOIg",
    "Jason Pizzino": "UCIb34uXDsfTq4PJKW0eztkA",
    "Michael Pizzino": "UCz2wzs4KacqHth7R_N5grgA",
    "Paul Barron Network": "UC4VPa7EOvObpyCRI4YKRQRw",
    "Crypto Capital Venture": "UCnMku7J_UtwlcSfZlIuQ3Kw",
}

def fetch_cmc_quotes(symbols: List[str]) -> Dict[str, Any]:
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_KEY} if CMC_KEY else {}
    params = {"symbol": ",".join(symbols), "convert": "USD"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", {})
    except Exception as e:
        # Fallback: estructura vacía
        data, _ = {}, e
    out = {}
    for sym in symbols:
        payload = data.get(sym, {})
        q = (payload.get("quote") or {}).get("USD", {})
        out[sym] = {
            "price": q.get("price"),
            "market_cap": q.get("market_cap"),
            "change_24h": q.get("percent_change_24h"),
            "last_updated": q.get("last_updated"),
        }
    return out

def fetch_youtube_latest(channel_id: str, max_results: int = 10) -> List[Dict[str, Any]]:
    if not YT_KEY:
        return []
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YT_KEY, "channelId": channel_id, "part": "snippet",
        "order": "date", "maxResults": max_results, "type": "video"
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        items = r.json().get("items", [])
        out = []
        for it in items:
            if 'id' in it and 'videoId' in it['id']:
                video_id = it['id']['videoId']
                # Fetch full description
                video_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={YT_KEY}"
                v_r = requests.get(video_url, timeout=30)
                v_r.raise_for_status()
                v_data = v_r.json().get("items", [])
                description = v_data[0]['snippet']['description'] if v_data else ''
                out.append({
                    "videoId": video_id,
                    "title": it["snippet"]["title"],
                    "publishedAt": it["snippet"]["publishedAt"],
                    "description": description
                })
        return out
    except Exception:
        return []

def three_bar_signal_yf(ticker: str, timeframe: str = "3D") -> str:
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
    closes = ohlc["Close"].iloc[-4:-1]  # 3 barras completas
    up   = all(closes[i] > closes[i-1] for i in range(1, len(closes)))
    down = all(closes[i] < closes[i-1] for i in range(1, len(closes)))
    return "bullish" if up else "bearish" if down else "none"

def compute_technical_kpis(ticker: str) -> Dict[str, Any]:
    """KPIs técnicos legados: RSI(14), MACD(12,26,9), MA200 y relación Close vs MA200."""
    hist = yf.Ticker(ticker).history(period="400d", interval="1d")
    if hist.empty:
        return {"rsi14": None, "macd": None, "macd_signal": None, "ma200": None, "close_above_ma200": None}
    df = hist.copy()
    df["rsi14"] = ta.rsi(df["Close"], length=14)
    macd = ta.macd(df["Close"], fast=12, slow=26, signal=9)
    df["macd"] = macd["MACD_12_26_9"]
    df["macd_signal"] = macd["MACDs_12_26_9"]
    df["ma200"] = ta.sma(df["Close"], length=200)
    last = df.dropna().iloc[-1] if len(df.dropna()) else None
    if last is None:
        return {"rsi14": None, "macd": None, "macd_signal": None, "ma200": None, "close_above_ma200": None}
    return {
        "rsi14": round(float(last["rsi14"]), 2) if pd.notna(last["rsi14"]) else None,
        "macd": round(float(last["macd"]), 4) if pd.notna(last["macd"]) else None,
        "macd_signal": round(float(last["macd_signal"]), 4) if pd.notna(last["macd_signal"]) else None,
        "ma200": round(float(last["ma200"]), 2) if pd.notna(last["ma200"]) else None,
        "close_above_ma200": bool(last["Close"] > last["ma200"]) if pd.notna(last["ma200"]) else None,
    }

def fetch_fear_greed_index() -> Dict[str, Any]:
    # API pública (alternative.me). Si falla, devuelve placeholder.
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=20)
        val = r.json()["data"][0]
        return {"value": int(val["value"]), "classification": val["value_classification"], "timestamp": val["timestamp"]}
    except Exception:
        return {"value": 50, "classification": "Neutral", "timestamp": None}

def collect_youtube() -> Dict[str, Any]:
    out = {}
    for name, ch in YT_CHANNELS.items():
        out[name] = fetch_youtube_latest(ch, max_results=10)
        time.sleep(1)  # Para evitar límites de tasa
    return out

def main():
    # 1) CMC: precios rápidos y 24h
    cmc = fetch_cmc_quotes(list(COINS.values()))

    # 2) 3-bar + KPIs técnicos legados
    three_bar, technical = {}, {}
    for sym, yf_t in YF_TICKERS.items():
        three_bar[sym] = {"timeframe": "3D", "signal": three_bar_signal_yf(yf_t, "3D")}
        technical[sym] = compute_technical_kpis(yf_t)
        time.sleep(0.2)

    # 3) YouTube últimos videos
    youtube = collect_youtube()

    # 4) Sentimiento/ciclo
    fgi = fetch_fear_greed_index()  # sentimiento externo
    sentiment = {"classification": fgi["classification"].lower(), "fear_greed_index": fgi["value"]}
    cycle = {"average_cycle": 0.5}  # placeholder si no tienes tu fuente de ciclo

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coins": list(COINS.keys()),
        "cmc": cmc,
        "three_bar": three_bar,
        "technical": technical,      # <<< KPIs legados
        "youtube": youtube,
        "sentiment": sentiment,
        "cycle": cycle,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
