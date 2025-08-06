"""
analysis_engine.py

This module reads the raw data produced by collect_data.py and derives
composite risk scores and investment recommendations for each tracked
cryptocurrency. It outputs the analysis to a JSON file and generates
a compact HTML summary suitable for inclusion in an email report. The
analysis uses weighted factors combining sentiment, technical and cycle
indicators as described in the project requirements.
"""

import json
import os
from datetime import datetime
from typing import Dict, Tuple


# Weighting scheme for the composite risk calculation. Values must sum
# to 1.0. Adjust these weights to tune the relative importance of each
# component. The default weights reflect the specification provided by
# the user: 25% sentiment, 25% technical, 30% cycle, 20% social.
WEIGHTS = {
    "sentiment": 0.25,
    "technical": 0.25,
    "cycle": 0.30,
    "social": 0.20,
}


def compute_component_scores(data: Dict) -> Tuple[float, Dict[str, float]]:
    """Compute the composite risk for each coin and the portfolio.

    Args:
        data: Parsed JSON data from data.json.

    Returns:
        A tuple containing the portfolio risk (float) and a dictionary
        mapping coin symbols to their individual risk scores.
    """
    fear_greed = float(data.get("fear_greed_index", 50))
    # Sentiment risk is high when the index shows greed (higher values => lower risk)
    sentiment_risk = 1.0 - (fear_greed / 100.0)
    btc_dominance = float(data.get("btc_dominance", 50))
    # Social risk is proportional to Bitcoin dominance: high dominance implies
    # that altcoins may carry higher relative risk.
    social_risk = btc_dominance / 100.0
    coin_scores: Dict[str, float] = {}
    total = 0.0
    for symbol, coin in data.get("coins", {}).items():
        # Safely handle missing or null values for technical and cycle scores.
        # If the value is None, default to a neutral 0.5 before converting to float.
        tech_risk_value = coin.get("technical_risk")
        tech_risk = float(tech_risk_value if tech_risk_value is not None else 0.5)
        cycle_score_value = coin.get("cycle_score")
        cycle_score = float(cycle_score_value if cycle_score_value is not None else 0.5)
        # Combine component scores
        risk = (
            WEIGHTS["sentiment"] * sentiment_risk
            + WEIGHTS["technical"] * tech_risk
            + WEIGHTS["cycle"] * cycle_score
            + WEIGHTS["social"] * social_risk
        )
        coin_scores[symbol] = risk
        total += risk
    portfolio_risk = total / len(data.get("coins", {})) if data.get("coins") else 0.5
    return portfolio_risk, coin_scores


def derive_recommendation(risk: float) -> str:
    """Convert a risk score into a buy/hold/sell recommendation.

    Thresholds can be tuned as desired. Lower risk favours buying,
    moderate risk implies holding and high risk suggests taking profit.
    """
    if risk < 0.4:
        return "Comprar"
    if risk < 0.6:
        return "Mantener"
    return "Vender"


def generate_email_summary(portfolio_risk: float, coin_scores: Dict[str, float]) -> str:
    """Create a simple HTML report summarising the analysis.

    This function constructs an HTML fragment that highlights the
    overall portfolio recommendation and provides a ranked list of
    recommendations for each coin. This HTML is suitable to embed
    directly into an email body.
    """
    # Sort coins by risk ascending (low risk first)
    sorted_coins = sorted(coin_scores.items(), key=lambda kv: kv[1])
    overall_rec = derive_recommendation(portfolio_risk)
    lines = [f"<h2>Recomendación general: <strong>{overall_rec}</strong></h2>"]
    lines.append(
        f"<p>Riesgo compuesto del portafolio: {portfolio_risk:.2f}</p>"
    )
    lines.append("<h3>Recomendaciones por activo:</h3>")
    lines.append("<ul>")
    for symbol, risk in sorted_coins:
        rec = derive_recommendation(risk)
        lines.append(
            f"<li><strong>{symbol}</strong>: {rec} (riesgo {risk:.2f})</li>"
        )
    lines.append("</ul>")
    return "\n".join(lines)


def main() -> None:
    """Entry point for computing the analysis and emitting outputs."""
    # Load the raw data produced by collect_data.py
    if not os.path.exists("data.json"):
        raise FileNotFoundError(
            "data.json not found. Please run collect_data.py before analysis_engine.py."
        )
    with open("data.json", "r", encoding="utf-8") as infile:
        data = json.load(infile)
    portfolio_risk, coin_scores = compute_component_scores(data)
    # Derive recommendations for each coin
    recommendations: Dict[str, str] = {
        symbol: derive_recommendation(score) for symbol, score in coin_scores.items()
    }
    # Build structured output
    analysis = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "portfolio_risk": portfolio_risk,
        "recommendations": recommendations,
        "scores": coin_scores,
    }
    with open("analysis.json", "w", encoding="utf-8") as outfile:
        json.dump(analysis, outfile, indent=2)
    # Generate HTML summary for email
    summary_html = generate_email_summary(portfolio_risk, coin_scores)
    with open("email_summary.html", "w", encoding="utf-8") as htmlfile:
        htmlfile.write(summary_html)


if __name__ == "__main__":
    main()
