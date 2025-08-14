# analysis_engine.py
import json
from datetime import datetime, timezone
from typing import Dict, Any, Tuple
import re
import yfinance as yf
import pandas as pd

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

# ------------------ Estrategias ------------------

def extract_strategies(description: str) -> list[str]:
    keywords = r'(strategy|estrategia|buy|sell|hold|DCA|bull|bear|accumulate|exit|position|trade)'
    matches = re.findall(r'[^.?!]*\b{}\b[^.?!]*[.?!]'.format(keywords), description, re.IGNORECASE)
    return list(set(matches))

# ------------------ Monthly Returns ------------------

def compute_monthly_returns(ticker: str, periods: int = 12) -> pd.DataFrame:
    hist = yf.download(ticker, period="1y", interval="1mo")
    if hist.empty:
        return pd.DataFrame()
    hist['Return'] = hist['Close'].pct_change() * 100
    hist = hist.dropna()
    hist.index = hist.index.strftime('%Y-%m')
    return hist[['Return']].tail(periods).round(2)

# ------------------ HTML ------------------

def generate_email_summary(data: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    three_bar = data.get("three_bar", {})
    cmc = data.get("cmc", {})
    tech = data.get("technical", {})
    yt = data.get("youtube", {})
    fgi = (data.get("sentiment") or {}).get("fear_greed_index", None)
    fgi_cls = (data.get("sentiment") or {}).get("classification", "")
    fgi_cls = fgi_cls.title() if isinstance(fgi_cls, str) else ""

    css = """
    body { font-family: Arial, sans-serif; background-color: #f4f4f9; color: #333; padding: 20px; }
    h1, h2, h3 { color: #2c3e50; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
    th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
    th { background-color: #3498db; color: white; }
    .positive { color: #27ae60; font-weight: bold; }
    .negative { color: #e74c3c; font-weight: bold; }
    .badge { padding: 2px 8px; border-radius: 6px; font-size: 12px; }
    .bull { background: #e6f7e6; color: #0a7d00; }
    .bear { background: #fdeaea; color: #a80606; }
    .none { background: #eee; color: #666; }
    ul { list-style-type: none; padding: 0; }
    li { margin: 10px 0; background: #ecf0f1; padding: 10px; border-radius: 5px; }
    .strategy { background: #fff3cd; padding: 5px; border-left: 4px solid #ffc107; margin-top: 5px; }
    .legend { font-size: 0.8em; color: #7f8c8d; font-style: italic; margin-top: 5px; }
    @media (max-width: 600px) { table { font-size: 12px; } }
    """

    lines = []
    lines.append("<!DOCTYPE html>")
    lines.append('<html lang="es"><head><meta charset="UTF-8" />')
    lines.append("<title>Resumen de inversión en criptomonedas</title>")
    lines.append(f"<style>{css}</style>")
    lines.append("</head><body>")
    lines.append("<h1>Resumen de inversión en criptomonedas</h1>")
    lines.append("<p class='muted'>Generado: {}</p>".format(datetime.now(timezone.utc).isoformat()))
    lines.append("<h2>Riesgo del portafolio: {:.2f}% — {}</h2>".format(
        analysis["portfolio_risk"] * 100, derive_recommendation(analysis["portfolio_risk"])
    ))
    lines.append("<p class='legend'>Riesgo del portafolio: Media ponderada de componentes; <40% = Bajo (Comprar), 40-60% = Medio (Mantener), >60% = Alto (Vender).</p>")

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
        price_str = "N/A" if price_val is None else "$" + format(price_val, ".2f")
        ch24_str = "N/A" if ch24_val is None else format(ch24_val, ".2f") + "%"
        ch_class = "positive" if ch24_val and ch24_val > 0 else "negative" if ch24_val and ch24_val < 0 else ""

        rsi_str = "N/A" if t.get('rsi14') is None else str(t['rsi14'])
        macd_str = "N/A" if t.get('macd') is None else str(t['macd'])
        macds_str = "N/A" if t.get('macd_signal') is None else str(t['macd_signal'])
        ma_str = "N/A" if t.get('close_above_ma200') is None else ('Sí' if t['close_above_ma200'] else 'No')

        lines.append(f"<tr>"
                     f"<td>{sym}</td>"
                     f"<td>{price_str}</td>"
                     f"<td class='{ch_class}'>{ch24_str}</td>"
                     f"<td>{rsi_str}</td>"
                     f"<td>{macd_str}</td>"
                     f"<td>{macds_str}</td>"
                     f"<td>{ma_str}</td>"
                     f"<td><span class='badge {cls}'>{sig}</span></td>"
                     f"<td>{score * 100:.2f}%</td>"
                     f"<td>{rec}</td>"
                     f"</tr>")

    lines.append("</tbody></table>")
    lines.append("<p class='legend'>RSI14: Índice de fuerza relativa; >70 = Sobrecomprado (posible venta), <30 = Sobrevendido (posible compra).</p>")
    lines.append("<p class='legend'>MACD y Sig: Línea MACD vs señal; MACD > Sig = Momentum alcista, MACD < Sig = Momentum bajista.</p>")
    lines.append("<p class='legend'>MA200▲: Cierre por encima de MA200 = Tendencia alcista, por debajo = Bajista.</p>")
    lines.append("<p class='legend'>3-bar: Señal de 3 barras consecutivas alcistas (bullish) o bajistas (bearish).</p>")

    # Sección Sentiment & Ciclo
    lines.append("<h3>Sentiment & Ciclo</h3>")
    lines.append("<table><thead><tr><th>Fear & Greed</th><th>Clasificación</th><th>Ciclo (0-1)</th></tr></thead><tbody>")
    lines.append("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
        "N/A" if fgi is None else fgi,
        fgi_cls,
        (data.get("cycle") or {}).get("average_cycle", "N/A")
    ))
    lines.append("</tbody></table>")
    lines.append("<p class='legend'>Fear & Greed: Sentimiento del mercado; Bajo (<25) = Miedo (oportunidad compra), Alto (>75) = Codicia (riesgo).</p>")
    lines.append("<p class='legend'>Ciclo: 0 = Pico (alto riesgo), 1 = Valle (bajo riesgo).</p>")

    # Monthly Returns Table for BTC and ETH
    lines.append("<h3>Monthly Returns (%)</h3>")
    for ticker in ['BTC-USD', 'ETH-USD']:
        monthly_df = compute_monthly_returns(ticker)
        if not monthly_df.empty:
            lines.append(f"<h4>{ticker}</h4>")
            lines.append("<table><thead><tr><th>Mes</th><th>Return (%)</th></tr></thead><tbody>")
            for month, row in monthly_df.iterrows():
                ret = row['Return']
                ret_class = "positive" if ret > 0 else "negative" if ret < 0 else ""
                lines.append(f"<tr><td>{month}</td><td class='{ret_class}'>{ret}</td></tr>")
            lines.append("</tbody></table>")
        else:
            lines.append(f"<p>No data for {ticker}</p>")

    # Estrategias Detectadas
    lines.append("<h3>Estrategias Detectadas de Analistas</h3>")
    all_strategies = []
    for items in yt.values():
        for it in items:
            desc = it.get("description", "")
            strategies = extract_strategies(desc)
            all_strategies.extend(strategies)
    unique_strategies = list(set(all_strategies))
    if unique_strategies:
        lines.append("<ul>")
        for strat in unique_strategies:
            lines.append(f"<li class='strategy'>{strat}</li>")
        lines.append("</ul>")
    else:
        lines.append("<p>No estrategias detectadas.</p>")

    lines.append("</body></html>")
    return "\n".join(lines)

# ------------------ Dashboard interactivo ------------------

def generate_dashboard_html(data: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    html = generate_email_summary(data, analysis)
    # Agregar Chart.js y script para gráficos
    html = html.replace('</head>', '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script></head>')
    # Embed data para JS
    coins = data.get("coins", [])
    rsi_data = [data["technical"].get(sym, {}).get("rsi14", 0) for sym in coins]
    risk_data = [analysis["scores"].get(sym, 0) * 100 for sym in coins]
    labels = json.dumps(coins)
    rsi_json = json.dumps(rsi_data)
    risk_json = json.dumps(risk_data)
    html += f"""
    <h3>Gráficos Interactivos</h3>
    <canvas id="rsiChart" width="400" height="200"></canvas>
    <canvas id="riskChart" width="400" height="200"></canvas>
    <script>
        var ctx1 = document.getElementById('rsiChart').getContext('2d');
        new Chart(ctx1, {{
            type: 'bar',
            data: {{ labels: {labels}, datasets: [{{ label: 'RSI14', data: {rsi_json}, backgroundColor: '#3498db' }}] }},
            options: {{ scales: {{ y: {{ beginAtZero: true, max: 100 }} }} }}
        }});
        var ctx2 = document.getElementById('riskChart').getContext('2d');
        new Chart(ctx2, {{
            type: 'line',
            data: {{ labels: {labels}, datasets: [{{ label: 'Riesgo %', data: {risk_json}, borderColor: '#e74c3c' }}] }},
            options: {{ scales: {{ y: {{ beginAtZero: true, max: 100 }} }} }}
        }});
    </script>
    """
    return html

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
    dashboard_html = generate_dashboard_html(data, analysis)
    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(dashboard_html)

if __name__ == "__main__":
    main()
