"""
S&P 500 Weekly Dip Scanner
===========================
Scans all S&P 500 stocks under $50 for dip-buy signals using:
  - RSI < 35 (oversold)
  - Price below lower Bollinger Band
  - MACD histogram turning positive (momentum reversal)
  - Price above 200-day SMA (still in long-term uptrend)

Sends a weekly HTML email report with the results.

Requirements:
    pip install yfinance pandas ta schedule

Email setup:
    Set these environment variables (GitHub Secrets or local .env):
      EMAIL_SENDER      — your Gmail address
      EMAIL_PASSWORD    — Gmail App Password (not your login password)
                          Create one at: myaccount.google.com/apppasswords
      EMAIL_RECIPIENT   — destination email address
"""

import os
import smtplib
import logging
import schedule
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

import pandas as pd
import yfinance as yf
import ta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

EMAIL_CONFIG = {
    "sender":    os.environ.get("EMAIL_SENDER",    "pawel.marczas@gmail.com"),
    "password":  os.environ.get("EMAIL_PASSWORD",  "yesuagshiimnpofz"),
    "recipient": os.environ.get("EMAIL_RECIPIENT", "pawel.marczas@icloud.com"),
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
}

PRICE_CEILING = 250.0   # only include stocks below this price (USD)
RSI_THRESHOLD = 35     # RSI below this value = oversold
MIN_SIGNALS   = 2      # minimum signals required to appear in report
PERIOD_DAYS   = "1y"   # historical data window per stock

# ─── FETCH S&P 500 TICKERS ────────────────────────────────────────────────────

def get_sp500_tickers() -> list:
    """Scrape current S&P 500 constituents from Wikipedia."""
    log.info("Fetching S&P 500 constituent list from Wikipedia...")
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            storage_options={"User-Agent": "Mozilla/5.0"}
        )
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        log.info(f"Found {len(tickers)} tickers.")
        return tickers
    except Exception as e:
        log.error(f"Failed to fetch S&P 500 list: {e}")
        return []

# ─── SIGNAL DETECTION ─────────────────────────────────────────────────────────

def analyse_ticker(ticker: str) -> dict:
    """
    Download price history and compute dip signals.
    Returns a result dict if MIN_SIGNALS met and price < PRICE_CEILING, else None.
    """
    try:
        df = yf.download(
            ticker, period=PERIOD_DAYS, interval="1d",
            auto_adjust=True, progress=False, timeout=10
        )

        if df is None or len(df) < 60:
            return None

        close = df["Close"].squeeze()

        if not isinstance(close, pd.Series) or close.empty:
            return None

        current_price = float(close.iloc[-1])

        if current_price >= PRICE_CEILING or pd.isna(current_price):
            return None

        # ── Indicators ──────────────────────────────────────────────────────
        rsi_series = ta.momentum.RSIIndicator(close, window=14).rsi()
        bb         = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_lower   = bb.bollinger_lband()
        macd_ind   = ta.trend.MACD(close, window_fast=12, window_slow=26, window_sign=9)
        macd_hist  = macd_ind.macd_diff()
        sma200     = ta.trend.SMAIndicator(close, window=200).sma_indicator()

        # Guard against NaN at the tail
        for series in [rsi_series, bb_lower, macd_hist, sma200]:
            if pd.isna(series.iloc[-1]):
                return None

        rsi_val        = float(rsi_series.iloc[-1])
        bb_lower_val   = float(bb_lower.iloc[-1])
        macd_hist_now  = float(macd_hist.iloc[-1])
        macd_hist_prev = float(macd_hist.iloc[-2])
        sma200_val     = float(sma200.iloc[-1])

        # ── Signal scoring ───────────────────────────────────────────────────
        signals = []

        if rsi_val < RSI_THRESHOLD:
            signals.append(f"RSI oversold ({rsi_val:.1f})")

        if current_price < bb_lower_val:
            signals.append("Below Bollinger lower band")

        if macd_hist_prev < 0 and macd_hist_now > macd_hist_prev:
            signals.append("MACD histogram turning up")

        if current_price > sma200_val:
            signals.append("Above 200-day SMA (uptrend intact)")

        if len(signals) < MIN_SIGNALS:
            return None

        # ── 52-week stats ────────────────────────────────────────────────────
        high_52w      = float(close.rolling(252).max().iloc[-1])
        low_52w       = float(close.rolling(252).min().iloc[-1])
        pct_from_high = (current_price / high_52w - 1) * 100

        # ── Volume surge (today vs 20-day avg) ───────────────────────────────
        vol_today = float(df["Volume"].iloc[-1])
        vol_avg20 = float(df["Volume"].rolling(20).mean().iloc[-1])
        vol_ratio = vol_today / vol_avg20 if vol_avg20 > 0 else 1.0

        return {
            "ticker":        ticker,
            "price":         current_price,
            "rsi":           rsi_val,
            "signal_count":  len(signals),
            "signals":       signals,
            "pct_from_high": pct_from_high,
            "high_52w":      high_52w,
            "low_52w":       low_52w,
            "vol_ratio":     vol_ratio,
        }

    except Exception as e:
        log.debug(f"{ticker}: skipped ({e})")
        return None

# ─── FULL SCAN ────────────────────────────────────────────────────────────────

def run_scan() -> list:
    """Run the full S&P 500 scan and return sorted results."""
    tickers = get_sp500_tickers()
    if not tickers:
        log.error("No tickers to scan.")
        return []

    results = []
    total = len(tickers)
    for i, ticker in enumerate(tickers, 1):
        log.info(f"[{i}/{total}] Scanning {ticker}...")
        result = analyse_ticker(ticker)
        if result:
            results.append(result)

    results.sort(key=lambda x: (-x["signal_count"], x["rsi"]))
    log.info(f"Scan complete — {len(results)} dip candidates found.")
    return results

# ─── EMAIL REPORT ─────────────────────────────────────────────────────────────

def build_html_report(results: list) -> str:
    """Build a clean HTML email with the scan results."""
    date_str = datetime.now().strftime("%B %d, %Y")
    count    = len(results)

    rows_html = ""
    for r in results:
        signal_pills = "".join(
            f'<span style="display:inline-block;background:#E6F1FB;color:#0C447C;'
            f'font-size:11px;padding:2px 8px;border-radius:20px;margin:2px 3px 2px 0;">'
            f'{s}</span>'
            for s in r["signals"]
        )
        vol_flag = (
            f' <span style="color:#854F0B;font-size:11px">({r["vol_ratio"]:.1f}x vol)</span>'
            if r["vol_ratio"] > 1.5 else ""
        )
        rsi_color = "#A32D2D" if r["rsi"] < 30 else "#854F0B"
        rows_html += f"""
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:10px 8px;font-weight:500;color:#111;">{r['ticker']}</td>
          <td style="padding:10px 8px;">${r['price']:.2f}{vol_flag}</td>
          <td style="padding:10px 8px;color:{rsi_color};">{r['rsi']:.1f}</td>
          <td style="padding:10px 8px;color:#A32D2D;">{r['pct_from_high']:.1f}%</td>
          <td style="padding:10px 8px;white-space:nowrap;">${r['low_52w']:.2f} – ${r['high_52w']:.2f}</td>
          <td style="padding:10px 8px;">{signal_pills}</td>
        </tr>"""

    table_html = ""
    if count > 0:
        table_html = f"""
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead>
            <tr style="background:#f8f8f8;border-bottom:2px solid #e0e0e0;">
              <th style="padding:10px 8px;text-align:left;color:#555;">Ticker</th>
              <th style="padding:10px 8px;text-align:left;color:#555;">Price</th>
              <th style="padding:10px 8px;text-align:left;color:#555;">RSI</th>
              <th style="padding:10px 8px;text-align:left;color:#555;">From 52w High</th>
              <th style="padding:10px 8px;text-align:left;color:#555;">52w Range</th>
              <th style="padding:10px 8px;text-align:left;color:#555;">Signals</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>"""
    else:
        table_html = """
        <p style="text-align:center;color:#888;padding:2rem 0;">
          No dip signals found this week matching the criteria.
        </p>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px;">
  <div style="max-width:900px;margin:0 auto;background:#fff;border-radius:12px;
              overflow:hidden;border:1px solid #e0e0e0;">

    <div style="background:#0C447C;padding:24px 28px;">
      <h1 style="color:#fff;margin:0;font-size:20px;">S&P 500 Weekly Dip Scanner</h1>
      <p style="color:#B5D4F4;margin:6px 0 0;font-size:13px;">
        {date_str} &nbsp;·&nbsp; Stocks under ${PRICE_CEILING:.0f}
        &nbsp;·&nbsp; {count} candidate{"s" if count != 1 else ""} found
      </p>
    </div>

    <div style="padding:20px 28px 8px;">
      <p style="color:#555;font-size:13px;line-height:1.6;margin:0 0 16px;">
        Stocks below triggered at least <strong>{MIN_SIGNALS} dip signals</strong>:
        RSI&nbsp;&lt;&nbsp;{RSI_THRESHOLD} (oversold), price below Bollinger lower band,
        MACD histogram turning positive, and/or price above 200-day SMA.
        <em>Screening tool only — not financial advice.</em>
      </p>
      {table_html}
    </div>

    <div style="padding:16px 28px;border-top:1px solid #eee;background:#fafafa;">
      <p style="color:#999;font-size:11px;margin:0;line-height:1.6;">
        Criteria: Price &lt; ${PRICE_CEILING} &nbsp;|&nbsp;
        RSI(14) &lt; {RSI_THRESHOLD} &nbsp;|&nbsp;
        Bollinger Bands(20,2) &nbsp;|&nbsp;
        MACD(12,26,9) &nbsp;|&nbsp;
        SMA(200) &nbsp;|&nbsp;
        Min {MIN_SIGNALS} signals required &nbsp;|&nbsp;
        Data: Yahoo Finance
      </p>
    </div>

  </div>
</body>
</html>"""


def send_email(html_body: str, result_count: int):
    """Send the HTML report via SMTP."""
    cfg     = EMAIL_CONFIG
    subject = (
        f"S&P 500 Dip Scanner — {result_count} signal"
        f"{'s' if result_count != 1 else ''} found "
        f"({datetime.now().strftime('%b %d, %Y')})"
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = cfg["sender"]
    msg["To"]      = cfg["recipient"]
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["sender"], cfg["password"])
            server.sendmail(cfg["sender"], cfg["recipient"], msg.as_string())
        log.info(f"Email sent successfully to {cfg['recipient']}")
    except Exception as e:
        log.error(f"Failed to send email: {e}")
        raise


# ─── WEEKLY JOB ───────────────────────────────────────────────────────────────

def weekly_job():
    log.info("=== Starting weekly S&P 500 dip scan ===")
    results = run_scan()
    html    = build_html_report(results)
    send_email(html, len(results))
    log.info("=== Weekly job complete ===")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # --schedule mode: run now then keep running every Monday at 07:00
    # default (no flag): run once and exit — correct for GitHub Actions
    if "--schedule" in sys.argv:
        log.info("Scheduler mode: running now, then every Monday at 07:00.")
        weekly_job()
        schedule.every().monday.at("07:00").do(weekly_job)
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        log.info("Single-run mode.")
        weekly_job()
