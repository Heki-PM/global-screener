#!/usr/bin/env python3
"""
Global Stock Screener — FMP + yfinance
Etap 1 : FMP /stock-screener  → wstępne zawężenie po marketCap + price
Etap 2 : FMP financial statements → weryfikacja EBITDA, ROIC, EPS, growth
Etap 3 : yfinance → SMI(10,3,3) W1 → sygnał
Etap 4 : HTML + JSON + TradingView export
"""

import os, json, time, math, requests, yfinance as yf
import pandas as pd, numpy as np
from datetime import datetime, timezone
from pathlib import Path

# ── KONFIGURACJA ──────────────────────────────────────────────────────────────
FMP_KEY = os.environ.get("FMP_API_KEY", "DjE0sr8vQerl3JfZTeHMYJjgoTXR4qgY")
DEBUG   = os.environ.get("DEBUG", "0") == "1"   # ustaw DEBUG=1 żeby widzieć powody odrzuceń

FILTERS = dict(
    market_cap_min      = 1_000_000_000,   # 1B (luźniej niż 10B — FMP darmowy plan)
    price_min           = 10,
    ebitda_margin_min   = 15.0,            # %
    roic_min            = 10.0,            # %
    cash_ops_min        = 1_000_000,
    eps_ttm_min         = 0.10,
    revenue_growth_min  = 5.0,             # %
    eps_growth_min      = 5.0,             # %
    ohlson_max          = 5.0,             # % (trochę luźniej)
)

SMI_K, SMI_D, SMI_SIG = 10, 3, 3
OVERSOLD = -40

EXCHANGES = [
    "NASDAQ","NYSE","AMEX",
    "EURONEXT","LSE","XETRA",
    "TSX","ASX","NSE","TSE","HKEX","SGX","KRX",
]

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def fmp_get(endpoint: str, params: dict = {}, timeout: int = 20) -> dict | list | None:
    """Wywołuje FMP API. Zwraca dane lub None przy błędzie."""
    try:
        r = requests.get(
            f"https://financialmodelingprep.com/api/v3/{endpoint}",
            params={"apikey": FMP_KEY, **params},
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json()
        if DEBUG:
            print(f"    [FMP {r.status_code}] {endpoint}: {r.text[:120]}")
    except Exception as e:
        if DEBUG:
            print(f"    [FMP ERR] {endpoint}: {e}")
    return None

def safe_float(val, default=0.0) -> float:
    try: return float(val) if val is not None else default
    except: return default

def safe_int(val, default=0) -> int:
    try: return int(val) if val is not None else default
    except: return default

# ── ETAP 1: FMP SCREENER ──────────────────────────────────────────────────────
def fetch_fmp_candidates() -> list[dict]:
    print("\n═══ ETAP 1: FMP Screener ═══")
    all_c, seen = [], set()

    for exchange in EXCHANGES:
        page, ex_n = 0, 0
        print(f"  {exchange} ...", end=" ", flush=True)
        while True:
            data = fmp_get("stock-screener", {
                "exchange":          exchange,
                "marketCapMoreThan": FILTERS["market_cap_min"],
                "priceMoreThan":     FILTERS["price_min"],
                "isEtf":             "false",
                "isActivelyTrading": "true",
                "limit":             250,
                "offset":            page * 250,
            })
            if not data or not isinstance(data, list):
                break
            for item in data:
                sym = item.get("symbol","")
                if sym and sym not in seen:
                    seen.add(sym)
                    item["_exchange"] = exchange
                    all_c.append(item)
                    ex_n += 1
            if len(data) < 250:
                break
            page += 1
            time.sleep(0.25)
        print(ex_n)
        time.sleep(0.2)

    print(f"\n  ✅ Kandydatów łącznie: {len(all_c)}")
    return all_c

# ── ETAP 2: WERYFIKACJA FUNDAMENTALNA ─────────────────────────────────────────
def ohlson_score(bs_curr: dict, bs_prev: dict, inc: dict, cf: dict) -> float | None:
    try:
        ta   = safe_float(bs_curr.get("totalAssets"),  1)
        tl   = safe_float(bs_curr.get("totalLiabilities"))
        ca   = safe_float(bs_curr.get("totalCurrentAssets"))
        cl   = safe_float(bs_curr.get("totalCurrentLiabilities"))
        ni   = safe_float(inc.get("netIncome"))
        ocf  = safe_float(cf.get("operatingCashFlow"))
        ta_p = safe_float(bs_prev.get("totalAssets"), 1)
        ni_p = safe_float(bs_prev.get("retainedEarnings"))

        x1 = math.log(max(ta, 1) / 1000)
        x2 = tl / ta
        x3 = (ca - cl) / ta
        x4 = cl / max(ca, 1)
        x5 = 1 if tl > ta else 0
        x6 = ni / ta
        x7 = ocf / ta
        x8 = 1 if ni < 0 and ni_p < 0 else 0
        x9 = (ni - ni_p) / (abs(ni) + abs(ni_p) + 1e-9)

        score = -1.32 - 0.407*x1 + 6.03*x2 - 1.43*x3 + 0.076*x4 \
                - 1.72*x5 - 2.37*x6 - 1.83*x7 + 0.285*x8 - 0.521*x9
        return round(100 / (1 + math.exp(-score)), 2)
    except:
        return None


def verify(symbol: str, fmp_item: dict) -> dict | None:
    """
    Pobiera dane finansowe z FMP i weryfikuje filtry.
    Zwraca dict z fundamentals lub None jeśli nie przechodzi.
    Używa income-statement + balance-sheet + cash-flow (dostępne na darmowym planie).
    ratios-ttm jako uzupełnienie (może nie być dostępne).
    """
    reject_reason = []

    # ── income statement ──
    inc_data = fmp_get(f"income-statement/{symbol}", {"limit": 2, "period": "annual"})
    inc  = inc_data[0] if inc_data and len(inc_data) > 0 else {}
    inc2 = inc_data[1] if inc_data and len(inc_data) > 1 else {}

    # ── balance sheet ──
    bs_data = fmp_get(f"balance-sheet-statement/{symbol}", {"limit": 2, "period": "annual"})
    bs   = bs_data[0] if bs_data and len(bs_data) > 0 else {}
    bs2  = bs_data[1] if bs_data and len(bs_data) > 1 else {}

    # ── cash flow ──
    cf_data = fmp_get(f"cash-flow-statement/{symbol}", {"limit": 1, "period": "annual"})
    cf = cf_data[0] if cf_data and len(cf_data) > 0 else {}

    # ── ratios TTM (bonus — może nie działać na free plan) ──
    ratios_data = fmp_get(f"ratios-ttm/{symbol}")
    ratios = ratios_data[0] if ratios_data and isinstance(ratios_data, list) and ratios_data else {}

    # Wyciągnij wartości — z ratios (TTM) lub z income statement (roczne)
    revenue      = safe_float(inc.get("revenue"), 1)
    revenue_prev = safe_float(inc2.get("revenue"), revenue)
    ebitda       = safe_float(inc.get("ebitda"))
    net_income   = safe_float(inc.get("netIncome"))
    eps          = safe_float(inc.get("eps") or fmp_item.get("lastAnnualEps"))
    cash_ops     = safe_float(cf.get("operatingCashFlow"))
    total_equity = safe_float(bs.get("totalStockholdersEquity"), 1)
    total_debt   = safe_float(bs.get("totalDebt"))
    invested_cap = total_equity + total_debt if (total_equity + total_debt) > 0 else 1

    # Wylicz wskaźniki
    ebitda_margin_pct = (ebitda / revenue * 100) if revenue > 0 else 0
    roic_pct          = (net_income / invested_cap * 100) if invested_cap > 0 else 0
    rev_growth_pct    = ((revenue - revenue_prev) / abs(revenue_prev) * 100) if revenue_prev != 0 else 0

    eps_prev    = safe_float(inc2.get("eps"))
    eps_growth_pct = ((eps - eps_prev) / abs(eps_prev) * 100) if eps_prev and eps_prev != 0 else 0

    # Preferuj ratios TTM jeśli dostępne
    if ratios:
        ebitda_margin_pct = safe_float(ratios.get("ebitdaPerRevenueTTM"), ebitda_margin_pct / 100) * 100
        roic_from_ratios  = safe_float(ratios.get("returnOnCapitalEmployedTTM"), roic_pct / 100)
        if roic_from_ratios != 0:
            roic_pct = roic_from_ratios * 100

    # ── FILTRY ────
    if eps < FILTERS["eps_ttm_min"]:
        reject_reason.append(f"EPS={eps:.2f}<{FILTERS['eps_ttm_min']}")

    if ebitda_margin_pct < FILTERS["ebitda_margin_min"]:
        reject_reason.append(f"EBITDA_M={ebitda_margin_pct:.1f}%<{FILTERS['ebitda_margin_min']}%")

    if roic_pct < FILTERS["roic_min"]:
        reject_reason.append(f"ROIC={roic_pct:.1f}%<{FILTERS['roic_min']}%")

    if cash_ops < FILTERS["cash_ops_min"]:
        reject_reason.append(f"CashOps={cash_ops:.0f}<{FILTERS['cash_ops_min']}")

    if rev_growth_pct < FILTERS["revenue_growth_min"]:
        reject_reason.append(f"RevGrowth={rev_growth_pct:.1f}%<{FILTERS['revenue_growth_min']}%")

    if eps_prev and eps_growth_pct < FILTERS["eps_growth_min"]:
        reject_reason.append(f"EPSGrowth={eps_growth_pct:.1f}%<{FILTERS['eps_growth_min']}%")

    ohlson = ohlson_score(bs, bs2, inc, cf)
    if ohlson is not None and ohlson > FILTERS["ohlson_max"]:
        reject_reason.append(f"Ohlson={ohlson:.1f}%>{FILTERS['ohlson_max']}%")

    if reject_reason:
        if DEBUG:
            print(f"    SKIP {symbol}: {', '.join(reject_reason)}")
        return None

    return {
        "eps":           round(eps, 4),
        "ebitda_margin": round(ebitda_margin_pct, 2),
        "roic":          round(roic_pct, 2),
        "cash_ops":      int(cash_ops),
        "rev_growth":    round(rev_growth_pct, 2),
        "eps_growth":    round(eps_growth_pct, 2),
        "ohlson":        ohlson,
    }

# ── ETAP 3: SMI ───────────────────────────────────────────────────────────────
def calc_smi(close: pd.Series, k=10, d=3, sig=3):
    ll  = close.rolling(k).min()
    hh  = close.rolling(k).max()
    mid = (hh + ll) / 2
    ds  = (close - mid).ewm(span=d, adjust=False).mean()
    dds = ds.ewm(span=d, adjust=False).mean()
    dif = (hh - ll).ewm(span=d, adjust=False).mean()
    dif2= dif.ewm(span=d, adjust=False).mean()
    smi_vals = np.where(dif2 != 0, 100 * dds / (0.5 * dif2), 0)
    smi_s    = pd.Series(smi_vals, index=close.index)
    return smi_s, smi_s.ewm(span=sig, adjust=False).mean()

def get_smi_signal(ticker: str):
    try:
        hist = yf.Ticker(ticker).history(period="2y", interval="1wk", auto_adjust=True)
        if hist.empty or len(hist) < 25:
            return None, 0.0, 0.0
        smi_s, sig_s = calc_smi(hist["Close"])
        s0,s1,s2 = smi_s.iloc[-1], smi_s.iloc[-2], smi_s.iloc[-3]
        e0,e1    = sig_s.iloc[-1], sig_s.iloc[-2]

        if s1 <= e1 and s0 > e0:
            sig_type = "STRONG BUY" if s1 < OVERSOLD else "BUY"
        elif s0 > s1 and s1 <= s2 and s0 < e0:
            sig_type = "TURNING UP"
        else:
            sig_type = None

        return sig_type, round(float(s0), 2), round(float(e0), 2)
    except:
        return None, 0.0, 0.0

# ── HTML ──────────────────────────────────────────────────────────────────────
CSS = """<style>
:root{--bg:#0f1117;--bg2:#1a1f2e;--bg3:#1e2530;--text:#e2e8f0;--muted:#64748b;
      --border:#2d3748;--green:#22c55e;--blue:#60a5fa;--purple:#a78bfa;--red:#f87171}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);padding:20px}
header{text-align:center;padding:32px 0 24px;border-bottom:1px solid var(--border);margin-bottom:28px}
header h1{font-size:1.8rem;font-weight:800}
header p{color:var(--muted);font-size:.88rem;margin-top:6px}
.stats{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;margin-bottom:24px}
.stat{background:var(--bg3);border-radius:10px;padding:12px 22px;text-align:center}
.stat-n{font-size:1.6rem;font-weight:800}
.stat-l{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-top:2px}
.green{color:var(--green)}.blue{color:var(--blue)}.purple{color:var(--purple)}
section{margin-bottom:34px}
section h2{font-size:1.05rem;font-weight:700;margin-bottom:12px;padding-left:2px}
table{width:100%;border-collapse:collapse;font-size:.81rem}
thead th{background:var(--bg3);padding:9px 10px;text-align:left;font-size:.68rem;
         text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
         border-bottom:1px solid var(--border);position:sticky;top:0}
tbody tr{border-bottom:1px solid var(--border)}
tbody tr:hover{background:var(--bg2)}
tbody td{padding:8px 10px}
.badge{display:inline-block;border-radius:5px;font-size:.68rem;font-weight:700;padding:2px 7px}
.bs{background:#22c55e22;color:var(--green)}.bb{background:#60a5fa22;color:var(--blue)}
.bt{background:#a78bfa22;color:var(--purple)}
.ticker{font-weight:800;font-size:.93rem}
.name{color:var(--muted);font-size:.76rem}
.num{font-variant-numeric:tabular-nums}
.pos{color:var(--green)}.neg{color:var(--red)}
.ex{font-size:.68rem;color:var(--muted);background:var(--bg3);border-radius:4px;padding:1px 5px}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
.fbox{background:var(--bg3);border-radius:10px;padding:14px 18px;margin-bottom:24px;
      font-size:.79rem;color:var(--muted);line-height:2}
.fbox strong{color:var(--text)}
</style>"""

def fmt_cap(v):
    if v>=1e12: return f"${v/1e12:.1f}T"
    if v>=1e9:  return f"${v/1e9:.1f}B"
    return f"${v/1e6:.0f}M"

def badge(s):
    if s=="STRONG BUY": return '<span class="badge bs">⚡ STRONG BUY</span>'
    if s=="BUY":        return '<span class="badge bb">▲ BUY</span>'
    return                     '<span class="badge bt">↗ TURNING UP</span>'

def pct_cell(v):
    cls = "pos" if v >= 0 else "neg"
    return f'<span class="{cls}">{v:+.1f}%</span>'

def table_rows(items):
    if not items:
        return '<tr><td colspan="12" style="text-align:center;padding:24px;color:var(--muted)">Brak wyników</td></tr>'
    rows = []
    for r in items:
        ohlson = f"{r['ohlson']:.1f}%" if r.get("ohlson") is not None else "—"
        rows.append(f"""<tr>
<td><span class="ticker"><a href="https://finance.yahoo.com/quote/{r['symbol']}" target="_blank">{r['symbol']}</a></span>
    <br><span class="name">{r.get('name','')[:28]}</span></td>
<td>{badge(r['signal'])}</td>
<td><span class="ex">{r.get('exchange','')}</span></td>
<td class="num">${r.get('price',0):.2f}</td>
<td class="num">{fmt_cap(r.get('market_cap',0))}</td>
<td class="num">{pct_cell(r.get('rev_growth',0))}</td>
<td class="num">{pct_cell(r.get('eps_growth',0))}</td>
<td class="num">{r.get('ebitda_margin',0):.1f}%</td>
<td class="num">{r.get('roic',0):.1f}%</td>
<td class="num">{r.get('eps',0):.2f}</td>
<td class="num">{ohlson}</td>
<td class="num">{r.get('smi_val',0):.1f} / {r.get('smi_sig',0):.1f}</td>
</tr>""")
    return "\n".join(rows)

THEAD = """<thead><tr>
<th>Spółka</th><th>Sygnał</th><th>Giełda</th><th>Cena</th><th>Market Cap</th>
<th>Rev Growth</th><th>EPS Growth</th><th>EBITDA M.</th><th>ROIC</th>
<th>EPS TTM</th><th>Ohlson</th><th>SMI/Sig</th>
</tr></thead>"""

def gen_screener(results, ts):
    strong  = [r for r in results if r["signal"]=="STRONG BUY"]
    buy     = [r for r in results if r["signal"]=="BUY"]
    turning = [r for r in results if r["signal"]=="TURNING UP"]

    fbox = f"""<div class="fbox">
<strong>Filtry:</strong>
Market Cap ≥ <strong>{FILTERS['market_cap_min']//1_000_000_000}B</strong> &nbsp;·&nbsp;
Cena ≥ <strong>${FILTERS['price_min']}</strong> &nbsp;·&nbsp;
EBITDA Margin ≥ <strong>{FILTERS['ebitda_margin_min']}%</strong> &nbsp;·&nbsp;
ROIC ≥ <strong>{FILTERS['roic_min']}%</strong> &nbsp;·&nbsp;
EPS ≥ <strong>{FILTERS['eps_ttm_min']}</strong> &nbsp;·&nbsp;
Rev Growth ≥ <strong>{FILTERS['revenue_growth_min']}%</strong> &nbsp;·&nbsp;
EPS Growth ≥ <strong>{FILTERS['eps_growth_min']}%</strong> &nbsp;·&nbsp;
Ohlson ≤ <strong>{FILTERS['ohlson_max']}%</strong> &nbsp;·&nbsp;
Cash Ops ≥ <strong>$1M</strong> &nbsp;·&nbsp;
SMI(10,3,3) W1
</div>"""

    def section(title, color, items):
        return f"""<section>
<h2 class="{color}">{title}</h2>
<table>{THEAD}<tbody>{table_rows(items)}</tbody></table>
</section>"""

    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Global Stock Screener</title>{CSS}</head><body>
<header><h1>🌍 Global Stock Screener</h1>
<p>SMI(10,3,3) · Tygodniowy · FMP + yfinance &nbsp;|&nbsp; {ts}</p></header>
<div class="stats">
<div class="stat"><div class="stat-n green">{len(strong)}</div><div class="stat-l">⚡ Strong BUY</div></div>
<div class="stat"><div class="stat-n blue">{len(buy)}</div><div class="stat-l">▲ BUY</div></div>
<div class="stat"><div class="stat-n purple">{len(turning)}</div><div class="stat-l">↗ Turning Up</div></div>
<div class="stat"><div class="stat-n">{len(results)}</div><div class="stat-l">Łącznie</div></div>
</div>
{fbox}
{section("⚡ Strong BUY — crossover z oversold (SMI < −40)", "green", strong)}
{section("▲ BUY — SMI crossover", "blue", buy)}
{section("↗ Turning Up — zmiana kierunku (pre-crossover)", "purple", turning)}
<footer style="text-align:center;color:var(--muted);font-size:.75rem;padding:40px 0 20px">
Dane: FMP + Yahoo Finance · Tylko informacyjne, nie stanowi rekomendacji inwestycyjnej
</footer></body></html>"""

def gen_index(results, ts):
    s = len([r for r in results if r["signal"]=="STRONG BUY"])
    b = len([r for r in results if r["signal"]=="BUY"])
    t = len([r for r in results if r["signal"]=="TURNING UP"])
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Global Screener</title>{CSS}
<style>
.hero{{text-align:center;padding:70px 20px}}
.hero h1{{font-size:2.4rem;font-weight:900;margin-bottom:10px}}
.hero p{{color:var(--muted);margin-bottom:40px}}
.cards{{display:flex;gap:18px;justify-content:center;flex-wrap:wrap;margin-bottom:44px}}
.card{{background:var(--bg3);border-radius:14px;padding:28px 36px;text-align:center;
       min-width:150px;border:1px solid var(--border);transition:transform .15s}}
.card:hover{{transform:translateY(-3px)}}
.card-n{{font-size:2.2rem;font-weight:900}}
.card-l{{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:4px}}
.btn{{display:inline-block;background:#3b82f6;color:#fff;border-radius:10px;
      padding:14px 32px;font-size:1rem;font-weight:700;text-decoration:none}}
.btn:hover{{background:#2563eb}}
.ts{{color:var(--muted);font-size:.8rem;margin-top:18px}}
</style></head><body>
<div class="hero">
<h1>🌍 Global Stock Screener</h1>
<p>SMI(10,3,3) · Tygodniowy · Filtry fundamentalne · Globalny zasięg</p>
<div class="cards">
<div class="card"><div class="card-n green">{s}</div><div class="card-l">⚡ Strong BUY</div></div>
<div class="card"><div class="card-n blue">{b}</div><div class="card-l">▲ BUY</div></div>
<div class="card"><div class="card-n purple">{t}</div><div class="card-l">↗ Turning Up</div></div>
<div class="card"><div class="card-n">{s+b+t}</div><div class="card-l">Łącznie</div></div>
</div>
<a href="screener.html" class="btn">📊 Otwórz pełny raport</a>
<div class="ts">Ostatnia aktualizacja: {ts}</div>
</div></body></html>"""

# ── TV EXPORT ─────────────────────────────────────────────────────────────────
EX_MAP = {"NASDAQ":"NASDAQ","NYSE":"NYSE","AMEX":"AMEX","EURONEXT":"EURONEXT",
          "LSE":"LSE","XETRA":"XETR","TSX":"TSX","ASX":"ASX",
          "NSE":"NSE","TSE":"TSE","HKEX":"HKEX","SGX":"SGX","KRX":"KRX"}

def tv(sym, exchange):
    pfx  = EX_MAP.get(exchange, exchange)
    base = sym.replace("-",".").split(".")[0]
    return f"{pfx}:{base}"

def save_tv(results):
    groups = {"strong":[], "buy":[], "turning":[], "all":[]}
    for r in results:
        t = tv(r["symbol"], r.get("exchange",""))
        groups["all"].append(t)
        if r["signal"]=="STRONG BUY": groups["strong"].append(t)
        elif r["signal"]=="BUY":      groups["buy"].append(t)
        else:                         groups["turning"].append(t)
    for name, tickers in groups.items():
        (RESULTS_DIR / f"tv_{name}.txt").write_text(",".join(tickers))
    print(f"  ✅ TV watchlists: {len(groups['all'])} tickerów")

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n🌍 Global Stock Screener — {ts}")
    print(f"   DEBUG={'ON' if DEBUG else 'OFF'} (ustaw env DEBUG=1 żeby widzieć powody odrzuceń)")

    # ETAP 1
    candidates = fetch_fmp_candidates()

    # ETAP 2 + 3
    print(f"\n═══ ETAP 2+3: Fundamenty + SMI ({len(candidates)} kandydatów) ═══")
    results, skipped, no_sig, errs = [], 0, 0, 0

    for i, cand in enumerate(candidates, 1):
        sym      = cand.get("symbol","")
        name     = cand.get("companyName","")
        price    = safe_float(cand.get("price"))
        mktcap   = safe_float(cand.get("marketCap"))
        exchange = cand.get("_exchange","")

        if not sym:
            continue

        if i % 25 == 0 or i == len(candidates):
            print(f"  [{i}/{len(candidates)}] ✅{len(results)} ❌{skipped} 〰{no_sig} ⚠{errs}")

        try:
            fund = verify(sym, cand)
            if fund is None:
                skipped += 1
                time.sleep(0.15)
                continue

            sig, smi_v, smi_s_v = get_smi_signal(sym)
            if sig is None:
                no_sig += 1
                time.sleep(0.2)
                continue

            results.append({
                "symbol": sym, "name": name, "exchange": exchange,
                "price": round(price,2), "market_cap": int(mktcap),
                "signal": sig, "smi_val": smi_v, "smi_sig": smi_s_v,
                **fund,
            })
            print(f"  ✅ {sym:12s} | {sig:12s} | SMI {smi_v:+.1f}")
            time.sleep(0.3)

        except Exception as e:
            errs += 1
            if DEBUG: print(f"  ⚠️  {sym}: {e}")
            time.sleep(0.5)

        time.sleep(0.1)

    # Sortowanie
    order = {"STRONG BUY":0, "BUY":1, "TURNING UP":2}
    results.sort(key=lambda r: (order.get(r["signal"],9), -r.get("market_cap",0)))

    # Statystyki
    strong_n  = sum(1 for r in results if r["signal"]=="STRONG BUY")
    buy_n     = sum(1 for r in results if r["signal"]=="BUY")
    turning_n = sum(1 for r in results if r["signal"]=="TURNING UP")

    print(f"\n═══ PODSUMOWANIE ═══")
    print(f"  ⚡ STRONG BUY : {strong_n}")
    print(f"  ▲  BUY       : {buy_n}")
    print(f"  ↗  TURNING UP: {turning_n}")
    print(f"  ❌ Odfiltrowane: {skipped} / {len(candidates)}")
    print(f"  〰  Bez sygnału: {no_sig}")
    print(f"  ⚠️  Błędy:       {errs}")

    # ETAP 4: Zapis
    print("\n═══ ETAP 4: Zapis ═══")
    (RESULTS_DIR/"results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    (RESULTS_DIR/"meta.json").write_text(json.dumps({
        "run_ts":ts,"total":len(results),"strong":strong_n,"buy":buy_n,"turning":turning_n,
        "candidates":len(candidates),"skipped":skipped,"no_signal":no_sig,
    }, indent=2))
    (RESULTS_DIR/"screener.html").write_text(gen_screener(results, ts))
    (RESULTS_DIR/"index.html").write_text(gen_index(results, ts))
    save_tv(results)
    print(f"\n🏁 Gotowe — {len(results)} sygnałów.")

if __name__ == "__main__":
    main()
