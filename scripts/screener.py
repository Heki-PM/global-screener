#!/usr/bin/env python3
"""
Global Stock Screener — FMP + yfinance
========================================
Etap 1: FMP /stock-screener  → zawęża globalny wszechświat (~80k spółek)
         do kandydatów spełniających twarde filtry fundamentalne
Etap 2: yfinance              → oblicza SMI(10,3,3) na interwale tygodniowym
         i klasyfikuje sygnał: STRONG BUY / BUY / TURNING UP
Etap 3: Generuje raporty HTML + TradingView watchlist export

Filtry (z obrazka):
  Market Cap          ≥ 10 000 000 000 (10B)
  Revenue growth 2Y   ≥ 5%
  EPS growth 2Y       ≥ 5%
  EPS Basic TTM       ≥ 0.10
  EBITDA Margin TTM   ≥ 15%
  Ohlson Score        ≤ 3%   (wyliczany z danych FMP)
  ROIC TTM            ≥ 10%
  Cash from Ops TTM   ≥ 1 000 000
  Price               ≥ 10
"""

import os
import json
import time
import math
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# KONFIGURACJA
# ──────────────────────────────────────────────────────────────────────────────
FMP_KEY = os.environ.get("FMP_API_KEY", "DjE0sr8vQerl3JfZTeHMYJjgoTXR4qgY")

# Filtry fundamentalne (etap 1 — FMP screener)
F = dict(
    market_cap_min        = 10_000_000_000,   # 10B
    price_min             = 10,
    ebitda_margin_min     = 15.0,             # %
    roic_min              = 10.0,             # %
    cash_ops_min          = 1_000_000,        # USD
    eps_ttm_min           = 0.10,
    revenue_growth_min    = 5.0,              # %  (szacunki 2Y)
    eps_growth_min        = 5.0,              # %  (szacunki 2Y)
    ohlson_max            = 3.0,              # %  prawdopodobieństwo bankructwa
)

# SMI parametry
SMI_K   = 10
SMI_D   = 3
SMI_SIG = 3
OVERSOLD_LEVEL = -40

# Geografie FMP (exchange parametr)
EXCHANGES = [
    "NASDAQ", "NYSE", "AMEX",            # USA
    "EURONEXT", "LSE", "XETRA",          # Europa
    "TSX",                                # Kanada
    "ASX",                                # Australia
    "NSE", "BSE",                         # Indie
    "TSE", "OSE",                         # Japonia / Norwegia
    "HKEX", "SGX", "KRX",               # Azja
]

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# ETAP 1: FMP — pobieranie kandydatów
# ──────────────────────────────────────────────────────────────────────────────

def fmp_screen_exchange(exchange: str, page: int = 0) -> list[dict]:
    """Jedno zapytanie do FMP stock screener dla danej giełdy."""
    url = "https://financialmodelingprep.com/api/v3/stock-screener"
    params = {
        "apikey":         FMP_KEY,
        "exchange":       exchange,
        "marketCapMoreThan": F["market_cap_min"],
        "priceMoreThan":  F["price_min"],
        "isEtf":          "false",
        "isActivelyTrading": "true",
        "limit":          250,
        "offset":         page * 250,
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r.json() if isinstance(r.json(), list) else []
    except Exception as e:
        print(f"  [FMP screener] {exchange} p{page}: {e}")
    return []


def fmp_get_ratios(symbol: str) -> dict:
    """Pobiera wskaźniki finansowe TTM z FMP."""
    url = f"https://financialmodelingprep.com/api/v3/ratios-ttm/{symbol}"
    try:
        r = requests.get(url, params={"apikey": FMP_KEY}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if data:
                return data[0]
    except Exception:
        pass
    return {}


def fmp_get_growth(symbol: str) -> dict:
    """Pobiera wskaźniki wzrostu (w tym forward estimates)."""
    url = f"https://financialmodelingprep.com/api/v3/financial-growth/{symbol}"
    try:
        r = requests.get(url, params={"apikey": FMP_KEY, "limit": 1}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if data:
                return data[0]
    except Exception:
        pass
    return {}


def fmp_get_income(symbol: str) -> dict:
    """Pobiera dane income statement TTM."""
    url = f"https://financialmodelingprep.com/api/v3/income-statement/{symbol}"
    try:
        r = requests.get(url, params={"apikey": FMP_KEY, "limit": 2, "period": "annual"}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if data:
                return data[0]
    except Exception:
        pass
    return {}


def fmp_get_cashflow(symbol: str) -> dict:
    """Pobiera dane cash flow TTM."""
    url = f"https://financialmodelingprep.com/api/v3/cash-flow-statement/{symbol}"
    try:
        r = requests.get(url, params={"apikey": FMP_KEY, "limit": 1, "period": "annual"}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if data:
                return data[0]
    except Exception:
        pass
    return {}


def fmp_get_balance(symbol: str) -> dict:
    """Pobiera balance sheet do Ohlson Score."""
    url = f"https://financialmodelingprep.com/api/v3/balance-sheet-statement/{symbol}"
    try:
        r = requests.get(url, params={"apikey": FMP_KEY, "limit": 2, "period": "annual"}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if data:
                return data
    except Exception:
        pass
    return []


def compute_ohlson_score(bs_list: list, inc: dict, cf: dict) -> float | None:
    """
    Uproszczony Ohlson O-Score → prawdopodobieństwo bankructwa (0–100%).
    Używamy 9 zmiennych modelu z 1980.
    Zwraca prawdopodobieństwo jako % (0–100).
    """
    try:
        if len(bs_list) < 1:
            return None
        bs = bs_list[0]
        bs_prev = bs_list[1] if len(bs_list) > 1 else bs

        total_assets     = bs.get("totalAssets", 0) or 1
        total_liab       = bs.get("totalLiabilities", 0) or 0
        current_assets   = bs.get("totalCurrentAssets", 0) or 0
        current_liab     = bs.get("totalCurrentLiabilities", 0) or 0
        net_income       = inc.get("netIncome", 0) or 0
        operating_cf     = cf.get("operatingCashFlow", 0) or 0
        revenue          = inc.get("revenue", 1) or 1
        ebit             = inc.get("operatingIncome", 0) or 0
        retained_earn    = bs.get("retainedEarnings", 0) or 0
        total_assets_prev = bs_prev.get("totalAssets", 1) or 1
        net_income_prev  = bs_prev.get("retainedEarnings", 0) or 0  # uproszczenie

        # Zmienne Ohlson
        x1 = math.log(total_assets / 1000) if total_assets > 0 else 0    # SIZE
        x2 = total_liab / total_assets                                     # TLTA
        x3 = (current_assets - current_liab) / total_assets               # WCTA
        x4 = current_liab / (current_assets if current_assets > 0 else 1) # CLCA
        x5 = 1 if total_liab > total_assets else 0                        # OENEG
        x6 = net_income / total_assets                                     # NITA
        x7 = operating_cf / total_assets                                   # FUTL
        x8 = 1 if net_income < 0 and net_income_prev < 0 else 0           # INTWO
        x9 = (net_income - net_income_prev) / (abs(net_income) + abs(net_income_prev) + 1e-9)  # CHIN

        score = (-1.32
                 - 0.407 * x1
                 + 6.03  * x2
                 - 1.43  * x3
                 + 0.076 * x4
                 - 1.72  * x5
                 - 2.37  * x6
                 - 1.83  * x7
                 + 0.285 * x8
                 - 0.521 * x9)

        prob = 1 / (1 + math.exp(-score))   # logit → prawdopodobieństwo
        return round(prob * 100, 2)
    except Exception:
        return None


def fetch_fmp_candidates() -> list[dict]:
    """Pobiera wszystkich kandydatów z FMP dla wszystkich giełd."""
    print("\n═══ ETAP 1: FMP Screener ═══")
    all_candidates = []
    seen = set()

    for exchange in EXCHANGES:
        print(f"  → {exchange} ...", end=" ", flush=True)
        page = 0
        ex_count = 0
        while True:
            batch = fmp_screen_exchange(exchange, page)
            if not batch:
                break
            for item in batch:
                sym = item.get("symbol", "")
                if sym and sym not in seen:
                    seen.add(sym)
                    item["_exchange"] = exchange
                    all_candidates.append(item)
                    ex_count += 1
            if len(batch) < 250:
                break
            page += 1
            time.sleep(0.3)
        print(f"{ex_count} spółek")
        time.sleep(0.2)

    print(f"\n  ✅ Łącznie kandydatów po FMP screener: {len(all_candidates)}")
    return all_candidates


# ──────────────────────────────────────────────────────────────────────────────
# ETAP 2: Głęboka weryfikacja fundamentalna + SMI
# ──────────────────────────────────────────────────────────────────────────────

def smi(close: pd.Series, k: int = 10, d: int = 3, sig: int = 3):
    """Oblicza SMI(k, d, sig) na bazie cen zamknięcia."""
    ll = close.rolling(k).min()
    hh = close.rolling(k).max()
    diff  = hh - ll
    delta = close - (hh + ll) / 2

    ds  = delta.ewm(span=d, adjust=False).mean()
    dds = ds.ewm(span=d, adjust=False).mean()
    dif = diff.ewm(span=d, adjust=False).mean()
    dif2= dif.ewm(span=d, adjust=False).mean()

    smi_line = np.where(dif2 != 0, 100 * dds / (0.5 * dif2), 0)
    smi_s    = pd.Series(smi_line, index=close.index)
    signal   = smi_s.ewm(span=sig, adjust=False).mean()
    return smi_s, signal


def classify_signal(smi_vals: pd.Series, sig_vals: pd.Series) -> str | None:
    """
    Zwraca typ sygnału lub None.
    STRONG BUY  : crossover (SMI przebija Signal od dołu) gdy SMI < -40
    BUY         : crossover (SMI przebija Signal od dołu)
    TURNING UP  : SMI rośnie ale jeszcze nie przekroczyło Signal
    """
    if len(smi_vals) < 4:
        return None

    s0, s1, s2 = smi_vals.iloc[-1], smi_vals.iloc[-2], smi_vals.iloc[-3]
    e0, e1     = sig_vals.iloc[-1],  sig_vals.iloc[-2]

    crossover = s1 <= e1 and s0 > e0

    if crossover and s1 < OVERSOLD_LEVEL:
        return "STRONG BUY"
    if crossover:
        return "BUY"
    # turning up: SMI nie przekroczyło jeszcze, ale zmienia kierunek w górę
    if s0 > s1 and s1 <= s2 and s0 < e0:
        return "TURNING UP"
    return None


def get_weekly_smi_signal(ticker: str) -> tuple[str | None, float, float]:
    """Pobiera dane tygodniowe z yfinance i oblicza sygnał SMI."""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="2y", interval="1wk", auto_adjust=True)
        if hist.empty or len(hist) < SMI_K + SMI_D * 2 + 10:
            return None, 0.0, 0.0
        smi_line, sig_line = smi(hist["Close"], SMI_K, SMI_D, SMI_SIG)
        signal_type = classify_signal(smi_line, sig_line)
        return signal_type, round(float(smi_line.iloc[-1]), 2), round(float(sig_line.iloc[-1]), 2)
    except Exception:
        return None, 0.0, 0.0


def verify_fundamentals(symbol: str, fmp_data: dict) -> dict | None:
    """
    Pobiera szczegółowe dane FMP i weryfikuje wszystkie filtry z obrazka.
    Zwraca dict z danymi lub None jeśli nie spełnia filtrów.
    """
    ratios  = fmp_get_ratios(symbol)
    growth  = fmp_get_growth(symbol)
    inc     = fmp_get_income(symbol)
    cf      = fmp_get_cashflow(symbol)
    bs_list = fmp_get_balance(symbol)

    # ── EPS Basic TTM ──
    eps = fmp_data.get("lastAnnualEps") or inc.get("eps") or 0
    if eps < F["eps_ttm_min"]:
        return None

    # ── EBITDA Margin TTM ──
    ebitda_margin = ratios.get("ebitdaPerRevenueTTM", 0) or 0
    ebitda_margin_pct = ebitda_margin * 100
    if ebitda_margin_pct < F["ebitda_margin_min"]:
        return None

    # ── ROIC TTM ──
    roic = ratios.get("returnOnCapitalEmployedTTM", 0) or 0
    roic_pct = roic * 100
    if roic_pct < F["roic_min"]:
        return None

    # ── Cash from Operations TTM ──
    cash_ops = cf.get("operatingCashFlow", 0) or 0
    if cash_ops < F["cash_ops_min"]:
        return None

    # ── Revenue growth (TTM jako proxy dla 2Y estimate) ──
    rev_growth = growth.get("revenueGrowth", 0) or 0
    rev_growth_pct = rev_growth * 100
    if rev_growth_pct < F["revenue_growth_min"]:
        return None

    # ── EPS growth ──
    eps_growth = growth.get("epsgrowth", 0) or 0
    eps_growth_pct = eps_growth * 100
    if eps_growth_pct < F["eps_growth_min"]:
        return None

    # ── Ohlson Score ──
    ohlson = None
    if bs_list:
        ohlson = compute_ohlson_score(bs_list, inc, cf)
        if ohlson is not None and ohlson > F["ohlson_max"]:
            return None

    return {
        "eps":             round(float(eps), 4),
        "ebitda_margin":   round(ebitda_margin_pct, 2),
        "roic":            round(roic_pct, 2),
        "cash_ops":        int(cash_ops),
        "rev_growth":      round(rev_growth_pct, 2),
        "eps_growth":      round(eps_growth_pct, 2),
        "ohlson":          ohlson,
    }


# ──────────────────────────────────────────────────────────────────────────────
# TradingView export
# ──────────────────────────────────────────────────────────────────────────────

EXCHANGE_MAP = {
    "NASDAQ": "NASDAQ", "NYSE": "NYSE", "AMEX": "AMEX",
    "EURONEXT": "EURONEXT", "LSE": "LSE", "XETRA": "XETR",
    "TSX": "TSX", "ASX": "ASX", "NSE": "NSE", "BSE": "BSE",
    "TSE": "TSE", "OSE": "OSE", "HKEX": "HKEX", "SGX": "SGX", "KRX": "KRX",
}

def to_tv_ticker(symbol: str, exchange: str) -> str:
    prefix = EXCHANGE_MAP.get(exchange, exchange)
    clean  = symbol.replace("-", ".").split(".")[0]
    return f"{prefix}:{clean}"


def save_tv_watchlists(results: list[dict]):
    strong = [r for r in results if r["signal"] == "STRONG BUY"]
    buy    = [r for r in results if r["signal"] == "BUY"]
    turning= [r for r in results if r["signal"] == "TURNING UP"]

    def tickers(lst): return [to_tv_ticker(r["symbol"], r.get("exchange","")) for r in lst]
    def write(path, lines): Path(path).write_text(",".join(lines))

    write(RESULTS_DIR / "tv_strong.txt",  tickers(strong))
    write(RESULTS_DIR / "tv_buy.txt",     tickers(buy))
    write(RESULTS_DIR / "tv_turning.txt", tickers(turning))
    write(RESULTS_DIR / "tv_all.txt",     tickers(results))
    print(f"  ✅ TradingView watchlists zapisane ({len(results)} tickerów)")


# ──────────────────────────────────────────────────────────────────────────────
# HTML GENERATOR
# ──────────────────────────────────────────────────────────────────────────────

CSS = """
<style>
:root {
  --bg: #0f1117; --bg2: #1a1f2e; --bg3: #1e2530;
  --text: #e2e8f0; --muted: #64748b; --border: #2d3748;
  --green: #22c55e; --blue: #60a5fa; --purple: #a78bfa;
  --red: #f87171; --yellow: #fbbf24;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 20px; }
header { text-align: center; padding: 32px 0 24px; border-bottom: 1px solid var(--border); margin-bottom: 32px; }
header h1 { font-size: 1.8rem; font-weight: 800; }
header p  { color: var(--muted); font-size: 0.9rem; margin-top: 6px; }
.stats { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin-bottom: 32px; }
.stat { background: var(--bg3); border-radius: 10px; padding: 12px 22px; text-align: center; }
.stat-n { font-size: 1.6rem; font-weight: 800; }
.stat-l { font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 2px; }
.green { color: var(--green); } .blue { color: var(--blue); } .purple { color: var(--purple); }
section { margin-bottom: 36px; }
section h2 { font-size: 1.1rem; font-weight: 700; margin-bottom: 14px; padding-left: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
thead th { background: var(--bg3); padding: 10px 12px; text-align: left; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); border-bottom: 1px solid var(--border); position: sticky; top: 0; }
tbody tr { border-bottom: 1px solid var(--border); }
tbody tr:hover { background: var(--bg2); }
tbody td { padding: 9px 12px; }
.badge { display: inline-block; border-radius: 5px; font-size: 0.7rem; font-weight: 700; padding: 2px 8px; }
.badge-strong { background: #22c55e22; color: var(--green); }
.badge-buy    { background: #60a5fa22; color: var(--blue); }
.badge-turn   { background: #a78bfa22; color: var(--purple); }
.ticker { font-weight: 800; font-size: 0.95rem; }
.name   { color: var(--muted); font-size: 0.78rem; }
.num    { font-variant-numeric: tabular-nums; }
.pos    { color: var(--green); }
.neg    { color: var(--red); }
.ex-tag { font-size: 0.7rem; color: var(--muted); background: var(--bg3); border-radius: 4px; padding: 1px 6px; }
a { color: inherit; text-decoration: none; }
a:hover { text-decoration: underline; }
.filters-box { background: var(--bg3); border-radius: 10px; padding: 16px 20px; margin-bottom: 28px; font-size: 0.8rem; color: var(--muted); line-height: 1.9; }
.filters-box strong { color: var(--text); }
@media (max-width: 768px) { table { font-size: 0.75rem; } thead th, tbody td { padding: 7px 6px; } }
</style>
"""

def fmt_cap(v):
    if v >= 1e12: return f"${v/1e12:.1f}T"
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"

def fmt_pct(v, pos=True):
    cls = "pos" if v >= 0 else "neg"
    return f'<span class="{cls}">{v:+.1f}%</span>'

def signal_badge(sig):
    if sig == "STRONG BUY": return '<span class="badge badge-strong">⚡ STRONG BUY</span>'
    if sig == "BUY":        return '<span class="badge badge-buy">▲ BUY</span>'
    return                         '<span class="badge badge-turn">↗ TURNING UP</span>'

def rows_html(items):
    if not items:
        return '<tr><td colspan="12" style="text-align:center;padding:24px;color:var(--muted)">Brak wyników</td></tr>'
    out = []
    for r in items:
        ohlson_str = f"{r['ohlson']:.1f}%" if r.get('ohlson') is not None else "—"
        out.append(f"""
        <tr>
          <td><span class="ticker"><a href="https://finance.yahoo.com/quote/{r['symbol']}" target="_blank">{r['symbol']}</a></span><br>
              <span class="name">{r.get('name','')[:28]}</span></td>
          <td>{signal_badge(r['signal'])}</td>
          <td><span class="ex-tag">{r.get('exchange','')}</span></td>
          <td class="num">${r.get('price',0):.2f}</td>
          <td class="num">{fmt_cap(r.get('market_cap',0))}</td>
          <td class="num">{fmt_pct(r.get('rev_growth',0))}</td>
          <td class="num">{fmt_pct(r.get('eps_growth',0))}</td>
          <td class="num">{r.get('ebitda_margin',0):.1f}%</td>
          <td class="num">{r.get('roic',0):.1f}%</td>
          <td class="num">{r.get('eps',0):.2f}</td>
          <td class="num">{ohlson_str}</td>
          <td class="num">{r.get('smi_val',0):.1f} / {r.get('smi_sig',0):.1f}</td>
        </tr>""")
    return "\n".join(out)


def generate_html(results: list[dict], run_ts: str) -> str:
    strong  = [r for r in results if r["signal"] == "STRONG BUY"]
    buy     = [r for r in results if r["signal"] == "BUY"]
    turning = [r for r in results if r["signal"] == "TURNING UP"]

    thead = """<thead><tr>
      <th>Spółka</th><th>Sygnał</th><th>Giełda</th><th>Cena</th>
      <th>Market Cap</th><th>Rev Growth</th><th>EPS Growth</th>
      <th>EBITDA Margin</th><th>ROIC</th><th>EPS TTM</th>
      <th>Ohlson</th><th>SMI / Signal</th>
    </tr></thead>"""

    filters_html = f"""
    <div class="filters-box">
      <strong>Aktywne filtry:</strong>
      Market Cap ≥ <strong>10B</strong> &nbsp;·&nbsp;
      Cena ≥ <strong>$10</strong> &nbsp;·&nbsp;
      Revenue growth ≥ <strong>5%</strong> &nbsp;·&nbsp;
      EPS growth ≥ <strong>5%</strong> &nbsp;·&nbsp;
      EPS TTM ≥ <strong>0.10</strong> &nbsp;·&nbsp;
      EBITDA Margin ≥ <strong>15%</strong> &nbsp;·&nbsp;
      ROIC ≥ <strong>10%</strong> &nbsp;·&nbsp;
      Ohlson ≤ <strong>3%</strong> &nbsp;·&nbsp;
      Cash from Ops ≥ <strong>$1M</strong> &nbsp;·&nbsp;
      SMI(10,3,3) W1: <strong>BUY / STRONG BUY / TURNING UP</strong>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Global Stock Screener</title>
{CSS}
</head>
<body>
<header>
  <h1>🌍 Global Stock Screener</h1>
  <p>SMI(10,3,3) · Tygodniowy · Filtry fundamentalne FMP &nbsp;|&nbsp; {run_ts}</p>
</header>

<div class="stats">
  <div class="stat"><div class="stat-n green">{len(strong)}</div><div class="stat-l">⚡ Strong BUY</div></div>
  <div class="stat"><div class="stat-n blue">{len(buy)}</div><div class="stat-l">▲ BUY</div></div>
  <div class="stat"><div class="stat-n purple">{len(turning)}</div><div class="stat-l">↗ Turning Up</div></div>
  <div class="stat"><div class="stat-n">{len(results)}</div><div class="stat-l">Łącznie</div></div>
</div>

{filters_html}

<section>
  <h2 class="green">⚡ Strong BUY — SMI crossover z oversold (&lt; −40)</h2>
  <table>{thead}<tbody>{rows_html(strong)}</tbody></table>
</section>

<section>
  <h2 class="blue">▲ BUY — SMI crossover</h2>
  <table>{thead}<tbody>{rows_html(buy)}</tbody></table>
</section>

<section>
  <h2 class="purple">↗ Turning Up — zmiana kierunku (przed crossover)</h2>
  <table>{thead}<tbody>{rows_html(turning)}</tbody></table>
</section>

<footer style="text-align:center;color:var(--muted);font-size:0.75rem;padding:40px 0 20px">
  Dane: Financial Modeling Prep + Yahoo Finance (yfinance) &nbsp;·&nbsp;
  Wyłącznie informacyjne, nie stanowi rekomendacji inwestycyjnej
</footer>
</body>
</html>"""


def generate_index(results: list[dict], run_ts: str) -> str:
    """Strona główna — landing page z linkami."""
    strong  = len([r for r in results if r["signal"] == "STRONG BUY"])
    buy     = len([r for r in results if r["signal"] == "BUY"])
    turning = len([r for r in results if r["signal"] == "TURNING UP"])

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Global Screener — Start</title>
{CSS}
<style>
.hero {{ text-align:center; padding: 60px 20px; }}
.hero h1 {{ font-size: 2.4rem; font-weight: 900; margin-bottom: 10px; }}
.hero p  {{ color: var(--muted); font-size: 1rem; margin-bottom: 40px; }}
.cards {{ display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; margin-bottom: 50px; }}
.card {{ background: var(--bg3); border-radius: 14px; padding: 28px 36px; text-align: center; min-width: 160px; cursor: pointer; transition: transform .15s; border: 1px solid var(--border); }}
.card:hover {{ transform: translateY(-3px); }}
.card-n {{ font-size: 2.2rem; font-weight: 900; }}
.card-l {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin-top: 4px; }}
.btn {{ display:inline-block; background:#3b82f6; color:#fff; border-radius:10px; padding:14px 32px; font-size:1rem; font-weight:700; text-decoration:none; }}
.btn:hover {{ background:#2563eb; }}
.ts {{ color: var(--muted); font-size: 0.8rem; margin-top: 20px; }}
</style>
</head>
<body>
<div class="hero">
  <h1>🌍 Global Stock Screener</h1>
  <p>SMI(10,3,3) · Tygodniowy · Filtry fundamentalne · Globalne pokrycie</p>

  <div class="cards">
    <div class="card"><div class="card-n green">{strong}</div><div class="card-l">⚡ Strong BUY</div></div>
    <div class="card"><div class="card-n blue">{buy}</div><div class="card-l">▲ BUY</div></div>
    <div class="card"><div class="card-n purple">{turning}</div><div class="card-l">↗ Turning Up</div></div>
    <div class="card"><div class="card-n">{strong+buy+turning}</div><div class="card-l">Łącznie sygnałów</div></div>
  </div>

  <a href="screener.html" class="btn">📊 Otwórz pełny raport</a>
  <div class="ts">Ostatnia aktualizacja: {run_ts}</div>
</div>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────────────────────
# GŁÓWNA PĘTLA
# ──────────────────────────────────────────────────────────────────────────────

def main():
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n🌍 Global Stock Screener — start: {run_ts}")
    print(f"   Filtry: MarketCap≥10B, EBITDA≥15%, ROIC≥10%, RevGrowth≥5%, "
          f"EPSGrowth≥5%, EPS≥0.1, Ohlson≤3%, CashOps≥1M")

    # ETAP 1: FMP — pobierz kandydatów wstępnie odfiltrowanych
    candidates = fetch_fmp_candidates()

    # ETAP 2: Głęboka weryfikacja + SMI
    print(f"\n═══ ETAP 2: Weryfikacja fundamentalna + SMI ═══")
    print(f"   Weryfikuję {len(candidates)} kandydatów...")

    results  = []
    skipped  = 0
    no_signal= 0
    errors   = 0
    total    = len(candidates)

    for i, cand in enumerate(candidates, 1):
        symbol   = cand.get("symbol", "")
        name     = cand.get("companyName", "")
        price    = cand.get("price", 0) or 0
        mktcap   = cand.get("marketCap", 0) or 0
        exchange = cand.get("_exchange", "")

        if not symbol:
            continue

        # Progress co 50 spółek
        if i % 50 == 0 or i == total:
            print(f"  [{i}/{total}] OK:{len(results)} Skip:{skipped} NoSig:{no_signal}")

        try:
            # Głęboka weryfikacja fundamentalna
            fundamentals = verify_fundamentals(symbol, cand)
            if fundamentals is None:
                skipped += 1
                time.sleep(0.1)
                continue

            # SMI signal
            signal_type, smi_val, smi_sig_val = get_weekly_smi_signal(symbol)
            if signal_type is None:
                no_signal += 1
                time.sleep(0.2)
                continue

            results.append({
                "symbol":       symbol,
                "name":         name,
                "exchange":     exchange,
                "price":        round(price, 2),
                "market_cap":   mktcap,
                "signal":       signal_type,
                "smi_val":      smi_val,
                "smi_sig":      smi_sig_val,
                **fundamentals,
            })
            print(f"  ✅ {symbol:12s} | {signal_type:12s} | SMI {smi_val:+.1f}")
            time.sleep(0.3)

        except Exception as e:
            errors += 1
            print(f"  ⚠️  {symbol}: {e}")
            time.sleep(0.5)
            continue

        time.sleep(0.1)

    # Sortowanie: STRONG BUY → BUY → TURNING UP, wewnątrz malejąco po market cap
    order = {"STRONG BUY": 0, "BUY": 1, "TURNING UP": 2}
    results.sort(key=lambda r: (order.get(r["signal"], 9), -r.get("market_cap", 0)))

    print(f"\n═══ PODSUMOWANIE ═══")
    strong_n  = sum(1 for r in results if r["signal"] == "STRONG BUY")
    buy_n     = sum(1 for r in results if r["signal"] == "BUY")
    turning_n = sum(1 for r in results if r["signal"] == "TURNING UP")
    print(f"  ⚡ STRONG BUY : {strong_n}")
    print(f"  ▲  BUY       : {buy_n}")
    print(f"  ↗  TURNING UP: {turning_n}")
    print(f"  ❌ Odfiltrowanych: {skipped}")
    print(f"  〰  Bez sygnału  : {no_signal}")
    print(f"  ⚠️  Błędy        : {errors}")

    # ETAP 3: Zapis wyników
    print("\n═══ ETAP 3: Zapis wyników ═══")

    # JSON
    (RESULTS_DIR / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    (RESULTS_DIR / "meta.json").write_text(json.dumps({
        "run_ts": run_ts, "total": len(results),
        "strong": strong_n, "buy": buy_n, "turning": turning_n,
        "candidates_checked": total, "filtered_out": skipped,
    }, indent=2))

    # HTML
    (RESULTS_DIR / "screener.html").write_text(generate_html(results, run_ts))
    (RESULTS_DIR / "index.html").write_text(generate_index(results, run_ts))

    # TradingView watchlists
    save_tv_watchlists(results)

    print(f"\n  ✅ Zapisano: results/index.html, results/screener.html")
    print(f"  ✅ JSON: results/results.json, results/meta.json")
    print(f"  ✅ TV watchlists: tv_strong.txt, tv_buy.txt, tv_turning.txt, tv_all.txt")
    print(f"\n🏁 Gotowe! {len(results)} sygnałów łącznie.")


if __name__ == "__main__":
    main()
