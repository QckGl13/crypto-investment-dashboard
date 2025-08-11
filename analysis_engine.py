# analysis_engine.py
import json
from datetime import datetime, timezone
from typing import Dict, Any, Tuple

# Pesos consolidando lo legado + nuevo (ajústalos si quieres)
WEIGHTS = {
    "sentiment": 0.20,     # Fear & Greed (clasificación/value)
    "technical": 0.40,     # RSI/MACD/MA200 + %24h como proxy momentum
    "cycle": 0.25,         # Promedio de ciclo (0 pico, 1 valle) -> se invierte
    "social": 0.05,        # Placeholder social
    "overlay_3bar": 0.10   # Ajuste suave adicional por señal 3-bar
}

# ------------------ Utilidades ------------------

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def derive_recommendation(risk: float) -> str:
    # <0.4 Compra, 0.4–0.6 Mantener, >0.6 Vender
    return "Comprar" if risk < 0.4 else ("Mantener" if risk < 0.6 else "Vender")

def norm(x: float, lo: float, hi: float) -> float:
    """Normaliza x a [0,1] entre lo..hi, con límites y nulos tolerados."""
    if x is None or hi == lo:
        return 0.5
    v = (x - lo) / (hi - lo)
    return max(0.0, min(1.0, v))

# ------------------ KPIs técnicos (legado) ------------------

def technical_risk_from_kpis(tech: Dict[str, Any], pct24: float | None) -> float:
    """
    Combina KPIs técnicos legados en una señal de riesgo:
    - RSI(14): >70 sobrecompra (riesgo↑), <30 sobreventa (riesgo↓)
    - MACD vs señal: MACD < signal (riesgo↑), > (riesgo↓)
    - MA200: cerrar por debajo (riesgo↑), por encima (riesgo↓)
    - 24h %: caídas fuertes -> riesgo↑ (proxy de momentum reciente)
    """
    rsi = tech.get("rsi14")
    macd = tech.get("macd")
    macds = tech.get("macd_signal")
    above_ma = tech.get("close_above_ma200")

    # RSI
    if rsi is None:
        rsi_risk = 0.5
    elif rsi >= 70:
        rsi_risk = 0.8
    elif rsi <= 30:
        rsi_risk = 0.2
    else:
        rsi_risk = norm(rsi, 30, 70)

    # MACD
    if macd is None or macds is None:
        macd_risk = 0.5
    else:
        macd_risk = 0.3 if macd > macds else 0.7

    # MA200
    if above_ma is None:
        ma_risk = 0.5
    else:
        ma_risk = 0.35 if above_ma else 0.65

    # %24h
    if pct24 is None:
        ch_risk = 0.5
    else:
        # -10% => 0.8 riesgo ; +10% => 0.2 riesgo (lineal)
        ch_risk = norm(-pct24, -10, 10) * 0.6 + 0.2

    return max(0.0, min(1.0, (rsi_risk + macd_risk + ma_risk + ch_risk) / 4))

# ------------------ Cálculo de riesgos ------------------

def compute_component_scores(data: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    coins = data.get("coins", [])
    sentiment_cls = (data.get("sentiment") or {}).get("classification", "neutral").lower()
    avg_cycle = (data.get("cycle") or {}).get("average_cycle", 0.5)  # 0=pico,1=valle
    three_bar = data.get("three_bar", {})
    cmc = data.get("cmc", {})
    technical = data.get("technical", {})

    sent_map = {"bearish": 0.65, "neutral": 0.50, "bullish": 0.35}
    sentiment_risk = sent_map.get(sentiment_cls, 0.50)
    cycle_risk = 1 - avg_cycle  # invertimos: 1 valle (bajo riesgo) -> 0; 0 pico -> 1

    coin_scores: Dict[str, float] = {}
    for sym in coins:
        # CoinMarketCap usa símbolos base (BTC, ETH…)
        c = cmc.get(sym.replace("USDT", ""), {})
        pct24 = c.get("change_24h")
        tech = technical.get(sym, {})

        tech_risk = technical_risk_from_kpis(tech, pct24)
        social_risk = 0.5  # placeholder

        base = (
            WEIGHTS["sentiment"] * sentiment_risk +
            WEIGHTS["technical"] * tech_risk +
            WEIGHTS["cycle"] * cycle_risk +
            WEIGHTS["social"] * social_risk
        )

        # Ajuste 3-bar (overlay suave)
        sig = (three_bar.get(sym) or {}).get("signal", "none")
        if sig == "bearish":
            base = min(1.0, base + WEIGHTS["overlay_3bar"] * 0.5)  # +0.05
        elif sig == "bullish":
            base = max(0.0, base - WEIGHTS["overlay_3bar"] * 0.5)  # -0.05

        coin_scores[sym] = base

    portfolio_risk = sum(coin_scores.values()) / max(1, len(coin_scores))
    return portfolio_risk, coin_scores

# ------------------ HTML ------------------

def generate_email_summary(data: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    three_bar = data.get("three_bar", {})
    cmc = data.get("cmc", {})
    tech = data.get("technical", {})
    yt = data.get("youtube", {})
    fgi = (data.get("sentiment") or {}).get("fear_greed_index", None)
    fgi_cls = (data.get("sentiment") or {}).get("classification", "")
    fgi_cls = fgi_cls.title() if isinstance(fgi_cls, str) else ""

    css = (
      "body{font-family:Arial,sans-serif;margin:0;padding:20px;background:#f5f7fa;color:#333}"
      "h1{color:#2c3e50}h2{color:#34495e}h3{color:#34495e}"
      "table{border-collapse:collapse;width:100%;margin-top:16px}"
      "th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#2c3e50;color:#fff}"
      "tr:nth-child(even){background:#f2f2f2}.badge{padding:2px 8px;border-radius:6px;font-size:12px}"
      ".bull{background:#e6f7e6;color:#0a7d00}.bear{background:#fdeaea;color:#a80606}.none{background:#eee;color:#666}"
      ".muted{color:#666;font-size:12px}"
    )

    lines = []
    lines.append("<!DOCTYPE html>")
    lines.append('<html lang="es"><head><meta charset="UTF-8" />')
    lines.append("<title>Resumen de inversión en criptomonedas</title>")
    lines.append("<style>" + css + "</style>")
    lines.append("</head><body>")
    lines.append("<h1>Resumen de inversión en criptomonedas</h1>")
    lines.append("<p class='muted'>Generado: {}</p>".format(datetime.now(timezone.utc).isoformat()))
    lines.append("<h2>Riesgo del portafolio: {:.2f}% — {}</h2>".format(
        analysis["portfolio_risk"] * 100, derive_recommendation(analysis["portfolio_risk"])
    ))

    # Tabla principal
    lines.append("<h3>Detalle por activo</h3>")
    lines.append(
        "<table><thead><tr>"
        "<th>Cripto</th><th>Precio</th><th>24h%</th>"
        "<th>RSI14</th><th>MACD</th><th>MACD Sig</th><th>MA200▲</th>"
        "<th>3-bar</th><th>Riesgo</th><th>Recomendación</th>"
        "</tr></thead><tbody>"
    )

    for sym, score in sorted(analysis["scores"].items(), key=lambda kv: kv[1], reverse=True):
        rec = analysis["recommendations"].get(sym, derive_recommendation(score))
        c = cmc.get(sym.replace("USDT", ""), {})
        t = tech.get(sym, {})
        sig = (three_bar.get(sym) or {}).get("signal", "none")
        cls = "bull" if sig == "bullish" else ("bear" if sig == "bearish" else "none")

        price_val = c.get("price")
        ch24_val = c.get("change_24h")
        price_str = "" if price_val is None else "$" + format(price_val, ".2f")
        ch24_str = "" if ch24_val is None else format(ch24_val, ".2f") + "%"

        lines.append("<tr>"
                     "<td>{}</td>"
                     "<td>{}</td>"
                     "<td>{}</td>"
                     "<td>{}</td>"
                     "<td>{}</td>"
                     "<td>{}</td>"
                     "<td>{}</td>"
                     "<td><span class='badge {}'>{}</span></td>"
                     "<td>{:.2f}%</td>"
                     "<td>{}</td>"
                     "</tr>".format(
                         sym,
                         price_str,
                         ch24_str,
                         "" if t.get("rsi14") is None else t["rsi14"],
                         "" if t.get("macd") is None else t["macd"],
                         "" if t.get("macd_signal") is None else t["macd_signal"],
                         "" if t.get("close_above_ma200") is None else ("Sí" if t["close_above_ma200"] else "No"),
                         cls, sig,
                         score * 100,
                         rec
                     ))

    lines.append("</tbody></table>")

    # Sección Sentiment & Ciclo
    lines.append("<h3>Sentiment & Ciclo</h3>")
    lines.append("<table><thead><tr><th>Fear & Greed</th><th>Clasificación</th><th>Ciclo (0-1)</th></tr></thead><tbody>")
    lines.append("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
        "" if fgi is None else fgi,
        fgi_cls,
        (data.get("cycle") or {}).get("average_cycle", None)
    ))
    lines.append("</tbody></table>")

    # Últimos videos (YouTube)
    lines.append("<h3>Últimos videos de analistas</h3>")
    for name, items in (data.get("youtube") or {}).items():
        lines.append("<p><b>{}</b></p>".format(name))
        if not items:
            lines.append("<p class='muted'>Sin datos o sin API key.</p>")
            continue
        lines.append("<ul>")
        for it in items[:5]:
            vid = it.get("videoId")
            title = it.get("title", "(sin título)")
            url = "https://www.youtube.com/watch?v={}".format(vid) if vid else "#"
            lines.append("<li><a href='{}' target='_blank' rel='noopener noreferrer'>{}</a> — {}</li>".format(
                url, title, it.get("publishedAt", "")
            ))
        lines.append("</ul>")

    lines.append("</body></html>")
    return "\n".join(lines)

# ------------------ Main ------------------

def main():
    data = load_json("data.json")
    portfolio_risk, coin_scores = compute_component_scores(data)
    analysis = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio_risk": portfolio_risk,
        "recommendations": {k: derive_recommendation(v) for k, v in coin_scores.items()},
        "scores": coin_scores,
    }
    with open("analysis.json", "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    html = generate_email_summary(data, analysis)
    with open("email_summary.html", "w", encoding="utf-8") as f:
        f.write(html)

if __name__ == "__main__":
    main()
