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
    pip install yfinance pandas pandas-ta schedule

Email setup:
    Fill in EMAIL_CONFIG below.
    Gmail users: enable 2FA and create an App Password at
    https://myaccount.google.com/apppasswords
"""

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import smtplib
import schedule
import time
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

EMAIL_CONFIG = {
    "sender":    "your_email@gmail.com",     # your sending address
    "password":  "your_app_password_here",   # Gmail App Password (not your login password)
    "recipient": "your_email@gmail.com",     # where to receive the report
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
}

PRICE_CEILING   = 50.0   # only stocks under this price
RSI_THRESHOLD   = 35     # RSI below this = oversold
MIN_SIGNALS     = 2      # stock needs at least this many signals to appear in report
PERIOD_DAYS     = "1y"   # how much history to download per stock

# ─── FETCH S&P 500 TICKERS ────────────────────────────────────────────────────

def get_sp500_tickers() -> list[str]:
    """Scrape current S&P 500 constituents from Wikipedia."""
    log.info("Fetching S&P 500 constituent list from Wikipedia...")
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        log.info(f"Found {len(tickers)} tickers.")
        return tickers
    except Exception as e:
        log.error(f"Failed to fetch S&P 500 list: {e}")
        return []

# ─── SIGNAL DETECTION ─────────────────────────────────────────────────────────

def analyse_ticker(ticker: str) -> dict | None:
    """
    Download price history and compute dip signals.
    Returns a dict if signals found and price < PRICE_CEILING, else None.
    """
    try:
        df = yf.download(ticker, period=PERIOD_DAYS, interval="1d",
                         auto_adjust=True, progress=False, timeout=10)
        if df is None or len(df) < 60:
            return None

        close = df["Close"].squeeze()
        current_price = float(close.iloc[-1])

        if current_price >= PRICE_CEILING:
            return None

        # ── Indicators ──────────────────────────────────────────────────────
        rsi_series   = ta.rsi(close, length=14)
        bb           = ta.bbands(close, length=20, std=2)
        macd_result  = ta.macd(close, fast=12, slow=26, signal=9)
        sma200       = ta.sma(close, length=200)

        if rsi_series is None or bb is None or macd_result is None or sma200 is None:
            return None

        rsi_val       = float(rsi_series.iloc[-1])
        bb_lower      = float(bb["BBL_20_2.0"].iloc[-1])
        macd_hist_now = float(macd_result["MACDh_12_26_9"].iloc[-1])
        macd_hist_prev= float(macd_result["MACDh_12_26_9"].iloc[-2])
        sma200_val    = float(sma200.iloc[-1])

        # ── Signal scoring ───────────────────────────────────────────────────
        signals = []

        if rsi_val < RSI_THRESHOLD:
            signals.append(f"RSI oversold ({rsi_val:.1f})")

        if current_price < bb_lower:
            signals.append("Below Bollinger lower band")

        if macd_hist_prev < 0 and macd_hist_now > macd_hist_prev:
            signals.append("MACD histogram turning up")

        if current_price > sma200_val:
            signals.append("Above 200-day SMA (uptrend intact)")

        if len(signals) < MIN_SIGNALS:
            return None

        # ── 52-week stats ────────────────────────────────────────────────────
        high_52w = float(close.rolling(252).max().iloc[-1])
        low_52w  = float(close.rolling(252).min().iloc[-1])
        pct_from_high = (current_price / high_52w - 1) * 100

        # ── Volume surge (today vs 20-day avg) ───────────────────────────────
        vol_today  = float(df["Volume"].iloc[-1])
        vol_avg20  = float(df["Volume"].rolling(20).mean().iloc[-1])
        vol_ratio  = vol_today / vol_avg20 if vol_avg20 > 0 else 1.0

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

def run_scan() -> list[dict]:
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
    log.info(f"Scan complete. Found {len(results)} dip candidates.")
    return results

# ─── EMAIL REPORT ─────────────────────────────────────────────────────────────

def build_html_report(results: list[dict]) -> str:
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
            f'<span style="color:#854F0B;font-size:11px"> '
            f'({r["vol_ratio"]:.1f}x avg vol)</span>'
            if r["vol_ratio"] > 1.5 else ""
        )
        rows_html += f"""
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:10px 8px;font-weight:500;color:#111;white-space:nowrap;">{r['ticker']}</td>
          <td style="padding:10px 8px;font-weight:500;">${r['price']:.2f}{vol_flag}</td>
          <td style="padding:10px 8px;color:{'#A32D2D' if r['rsi']<30 else '#854F0B'};">{r['rsi']:.1f}</td>
          <td style="padding:10px 8px;color:#A32D2D;">{r['pct_from_high']:.1f}%</td>
          <td style="padding:10px 8px;">${r['low_52w']:.2f} – ${r['high_52w']:.2f}</td>
          <td style="padding:10px 8px;">{signal_pills}</td>
        </tr>"""

    no_results_msg = ""
    if count == 0:
        no_results_msg = """
        <p style="text-align:center;color:#888;padding:2rem 0;">
          No dip signals found this week matching the criteria.
        </p>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px;">
  <div style="max-width:900px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e0e0e0;">

    <div style="background:#0C447C;padding:24px 28px;">
      <h1 style="color:#fff;margin:0;font-size:20px;">S&P 500 Weekly Dip Scanner</h1>
      <p style="color:#B5D4F4;margin:6px 0 0;font-size:13px;">
        {date_str} &nbsp;·&nbsp; Stocks under $50 &nbsp;·&nbsp; {count} candidates found
      </p>
    </div>

    <div style="padding:20px 28px 8px;">
      <p style="color:#555;font-size:13px;line-height:1.6;margin:0 0 16px;">
        Stocks below show at least <strong>{MIN_SIGNALS} dip signals</strong>:
        RSI&nbsp;&lt;&nbsp;{RSI_THRESHOLD} (oversold), price below Bollinger lower band,
        MACD histogram turning positive, and/or price above 200-day SMA.
        <em>This is a screening tool, not financial advice.</em>
      </p>

      {'<table style="width:100%;border-collapse:collapse;font-size:13px;">' + '''<thead><tr style="background:#f8f8f8;border-bottom:2px solid #e0e0e0;">
        <th style="padding:10px 8px;text-align:left;color:#555;font-weight:600;">Ticker</th>
        <th style="padding:10px 8px;text-align:left;color:#555;font-weight:600;">Price</th>
        <th style="padding:10px 8px;text-align:left;color:#555;font-weight:600;">RSI</th>
        <th style="padding:10px 8px;text-align:left;color:#555;font-weight:600;">From 52w High</th>
        <th style="padding:10px 8px;text-align:left;color:#555;font-weight:600;">52w Range</th>
        <th style="padding:10px 8px;text-align:left;color:#555;font-weight:600;">Signals</th>
      </tr></thead><tbody>''' + rows_html + '</tbody></table>' if count > 0 else no_results_msg}
    </div>

    <div style="padding:16px 28px;border-top:1px solid #eee;background:#fafafa;">
      <p style="color:#999;font-size:11px;margin:0;line-height:1.6;">
        Criteria: Price &lt; ${PRICE_CEILING} &nbsp;|&nbsp; RSI(14) &lt; {RSI_THRESHOLD}
        &nbsp;|&nbsp; Bollinger Bands(20,2) &nbsp;|&nbsp; MACD(12,26,9) &nbsp;|&nbsp; SMA(200)
        &nbsp;|&nbsp; Min {MIN_SIGNALS} signals required.
        Data from Yahoo Finance via yfinance. Not financial advice.
      </p>
    </div>

  </div>
</body>
</html>"""


def send_email(html_body: str, result_count: int):
    """Send the HTML report via SMTP."""
    cfg = EMAIL_CONFIG
    subject = (
        f"S&P 500 Dip Scanner — {result_count} signals found "
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
        log.info(f"Email sent to {cfg['recipient']}")
    except Exception as e:
        log.error(f"Failed to send email: {e}")


# ─── WEEKLY JOB ───────────────────────────────────────────────────────────────

def weekly_job():
    log.info("=== Starting weekly S&P 500 dip scan ===")
    results   = run_scan()
    html      = build_html_report(results)
    send_email(html, len(results))
    log.info("=== Weekly job complete ===")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Run immediately on start, then every Monday at 07:00
    log.info("S&P 500 Dip Scanner starting up...")
    log.info("Running initial scan now...")
    weekly_job()

    schedule.every().monday.at("07:00").do(weekly_job)
    log.info("Scheduler active — next run: Monday 07:00. Press Ctrl+C to stop.")

    while True:
        schedule.run_pending()
        time.sleep(60)
