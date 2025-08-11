def generate_email_summary(data: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    three_bar = data.get("three_bar", {})
    cmc = data.get("cmc", {})
    tech = data.get("technical", {})
    yt = data.get("youtube", {})
    fgi = (data.get("sentiment") or {}).get("fear_greed_index", None)
    fgi_cls = (data.get("sentiment") or {}).get("classification", "").title()

    css = (
      "body{font-family:Arial,sans-serif;margin:0;padding:20px;background:#f5f7fa;color:#333}"
      "h1{color:#2c3e50}h2{color:#34495e}h3{color:#34495e}"
      "table{border-collapse:collapse;width:100%;margin-top:16px}"
      "th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#2c3e50;color:#fff}"
      "tr:nth-child(even){background:#f2f2f2}.badge{padding:2px 8px;border-radius:6px;font-size:12px}"
      ".bull{background:#e6f7e6;color:#0a7d00}.bear{background:#fdeaea;color:#a80606}.none{background:#eee;color:#666}"
      ".muted{color:#666;font-size:12px}"
    )

    lines = [
        "<!DOCTYPE html>",
        '<html lang="es"><head><meta charset="UTF-8" />',
        "<title>Resumen de inversión en criptomonedas</title>",
        f"<style>{css}</style>",
        "</head><body>",
        "<h1>Resumen de inversión en criptomonedas</h1>",
        f"<p class='muted'>Generado: {datetime.now(timezone.utc).isoformat()}</p>",
        f"<h2>Riesgo del portafolio: {analysis['portfolio_risk']*100:.2f}% — {derive_recommendation(analysis['portfolio_risk'])}</h2>",
        "<h3>Detalle por activo</h3>",
        "<table><thead><tr>"
        "<th>Cripto</th><th>Precio</th><th>24h%</th>"
        "<th>RSI14</th><th>MACD</th><th>MACD Sig</th><th>MA200▲</th>"
        "<th>3-bar</th><th>Riesgo</th><th>Recomendación</th>"
        "</tr></thead><tbody>"
    ]

    for sym, score in sorted(analysis["scores"].items(), key=lambda kv: kv[1], reverse=True):
        rec = analysis["recommendations"].get(sym, derive_recommendation(score))
        c = cmc.get(sym.replace("USDT",""), {})
        t = tech.get(sym, {})
        sig = (three_bar.get(sym) or {}).get("signal", "none")
        cls = "bull" if sig=="bullish" else "bear" if sig=="bearish" else "none"

        # --- EVITA f-strings anidadas/backslashes en expresiones ---
        price_val = c.get("price")
        price_str = "" if price_val is None else "$" + format(price_val, ".2f")

        ch24_val = c.get("change_24h")
        ch24_str = "" if ch24_val is None else format(ch24_val, ".2f") + "%"

        lines.append(
            "<tr>"
            f"<td>{sym}</td>"
            f"<td>{price_str}</td>"
            f"<td>{ch24_str}</td>"
            f"<td>{'' if t.get('rsi14') is None else t['rsi14']}</td>"
            f"<td>{'' if t.get('macd') is None else t['macd']}</td>"
            f"<td>{'' if t.get('macd_signal') is None else t['macd_signal']}</td>"
            f"<td>{'' if t.get('close_above_ma200') is None else ('Sí' if t['close_above_ma200'] else 'No')}</td>"
            f"<td><span class='badge {cls}'>{sig}</span></td>"
            f"<td>{score*100:.2f}%</td>"
            f"<td>{rec}</td>"
            "</tr>"
        )
    lines.append("</tbody></table>")

    # Sección Sentiment & Ciclo
    lines.append("<h3>Sentiment & Ciclo</h3>")
    lines.append("<table><thead><tr><th>Fear & Greed</th><th>Clasificación</th><th>Ciclo (0-1)</th></tr></thead><tbody>")
    lines.append(f"<tr><td>{'' if fgi is None else fgi}</td><td>{fgi_cls}</td><td>{( (data.get('cycle') or {}).get('average_cycle',None) )}</td></tr>")
    lines.append("</tbody></table>")

    # Últimos videos (YouTube)
    lines.append("<h3>Últimos videos de analistas</h3>")
    for name, items in yt.items():
        lines.append(f"<p><b>{name}</b></p>")
        if not items:
            lines.append("<p class='muted'>Sin datos o sin API key.</p>")
            continue
        lines.append("<ul>")
        for it in items[:5]:
            vid = it.get("videoId")
            title = it.get("title","(sin título)")
            url = f"https://www.youtube.com/watch?v={vid}" if vid else "#"
            lines.append(f"<li><a href='{url}' target='_blank' rel='noopener noreferrer'>{title}</a> — {it.get('publishedAt','')}</li>")
        lines.append("</ul>")

    lines.append("</body></html>")
    return "\n".join(lines)
