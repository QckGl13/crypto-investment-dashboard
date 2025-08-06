# Crypto Investment Dashboard

This repository contains an automated cryptocurrency analysis and reporting system. It collects
real‑time market data, computes technical indicators and cycle metrics, and produces a
responsive dashboard hosted via **GitHub Pages**. A GitHub Actions workflow runs every
morning at 6:00 AM America/Mexico_City time to update the data, regenerate the analysis,
commit the new files, and send an email report.

## Features

* **Data collection**: prices, market capitalisation, 24h changes and global metrics from CoinGecko; Fear & Greed index from alternative.me; Bitcoin dominance and total market cap; technical indicators (RSI, MACD, Bollinger Bands) and Fibonacci levels computed from yfinance data; recent videos via YouTube RSS feeds.
* **Analysis engine**: derives composite risk scores per coin and for the overall portfolio, applying user‑defined weights to sentiment, technical, cycle and social factors. Converts risk scores into buy/hold/sell recommendations.
* **Dashboard**: interactive HTML page built with vanilla JavaScript and Chart.js, showing key metrics, technical charts, risk table and the latest videos from trusted analysts.
* **Email reporting**: rich‑text email summarising the day’s recommendations, sent automatically via SMTP. Recipients and server credentials are configured via repository secrets.
* **Automation**: GitHub Actions orchestrates the entire pipeline, ensuring the dashboard and email are refreshed daily without manual intervention.

## Setup

1. Fork or clone this repository.
2. In your repository settings, configure the following **Secrets**:
   * `EMAIL_USER` – SMTP username (email address).
   * `EMAIL_PASS` – SMTP password or application token.
   * `EMAIL_HOST` – SMTP server hostname.
   * `EMAIL_PORT` – SMTP server port (e.g. 587).
   * `EMAIL_TO` – Comma‑separated list of recipient email addresses.
3. Enable **GitHub Pages** for the repository (Settings → Pages) and set the source
   branch to `main` with the root directory. The `dashboard.html` file will serve as
   the homepage.
4. Review the daily email time in `.github/workflows/update.yml` and adjust the cron
   schedule if necessary. The current schedule runs at 11:00 UTC (06:00 AM America/Mexico_City).

## Development

To run the pipeline locally for testing:

```bash
python3 -m pip install -r requirements.txt
python3 collect_data.py
python3 analysis_engine.py
# Configure environment variables for send_email.py as needed
python3 send_email.py
```

After running `collect_data.py` and `analysis_engine.py`, open `dashboard.html` in your
browser to view the generated dashboard. Note that some APIs may enforce rate limits;
avoid running the scripts more frequently than once per hour.
