#!/usr/bin/env python3
"""
Global Fundamental Screener
=============================
Pobiera tickery z iShares ETF (USA/EU/Azja) + statyczna lista GPW
Filtruje po fundamentach (bez SMI):
  Market Cap  ≥ 1B
  Price       ≥ 10
  EPS TTM     ≥ 0.10
  EBITDA M.   ≥ 15%
  ROIC        ≥ 10%
  Rev Growth  ≥ 5% YoY
  Cash Ops    ≥ 1 000 000
  Ohlson      ≤ 5%
Generuje: index.html, screener.html, results.json, tv_watchlist.txt
"""

import os, json, time, math, io, requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

DEBUG      = os.environ.get("DEBUG", "0") == "1"
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

FILTERS = dict(
    market_cap_min     = 1_000_000_000,
    price_min          = 10.0,
    eps_ttm_min        = 0.10,
    ebitda_margin_min  = 15.0,
    roic_min           = 10.0,
    cash_ops_min       = 1_000_000,
    revenue_growth_min = 5.0,
    ohlson_max         = 5.0,
)

# ── ŹRÓDŁA TICKERÓW ───────────────────────────────────────────────────────────

ISHARES_URLS_US = {
    "IVV": "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/1467271812596.ajax?fileType=csv&fileName=IVV_holdings&dataType=fund",
    "IJR": "https://www.ishares.com/us/products/239774/ishares-core-sp-smallcap-etf/1467271812596.ajax?fileType=csv&fileName=IJR_holdings&dataType=fund",
    "IWM": "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund",
    "IWB": "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/1467271812596.ajax?fileType=csv&fileName=IWB_holdings&dataType=fund",
    "IWC": "https://www.ishares.com/us/products/239711/ishares-micro-cap-etf/1467271812596.ajax?fileType=csv&fileName=IWC_holdings&dataType=fund",
    "IWD": "https://www.ishares.com/us/products/239708/ishares-russell-1000-value-etf/1467271812596.ajax?fileType=csv&fileName=IWD_holdings&dataType=fund",
    "IWF": "https://www.ishares.com/us/products/239706/ishares-russell-1000-growth-etf/1467271812596.ajax?fileType=csv&fileName=IWF_holdings&dataType=fund",
    "IWS": "https://www.ishares.com/us/products/239714/ishares-russell-mid-cap-value-etf/1467271812596.ajax?fileType=csv&fileName=IWS_holdings&dataType=fund",
    "IWP": "https://www.ishares.com/us/products/239713/ishares-russell-mid-cap-growth-etf/1467271812596.ajax?fileType=csv&fileName=IWP_holdings&dataType=fund",
    "IJH": "https://www.ishares.com/us/products/239763/ishares-core-sp-midcap-etf/1467271812596.ajax?fileType=csv&fileName=IJH_holdings&dataType=fund",
    "IYW": "https://www.ishares.com/us/products/239816/ishares-us-technology-etf/1467271812596.ajax?fileType=csv&fileName=IYW_holdings&dataType=fund",
    "IYH": "https://www.ishares.com/us/products/239808/ishares-us-healthcare-etf/1467271812596.ajax?fileType=csv&fileName=IYH_holdings&dataType=fund",
    "IYF": "https://www.ishares.com/us/products/239735/ishares-us-financials-etf/1467271812596.ajax?fileType=csv&fileName=IYF_holdings&dataType=fund",
    "IYE": "https://www.ishares.com/us/products/239733/ishares-us-energy-etf/1467271812596.ajax?fileType=csv&fileName=IYE_holdings&dataType=fund",
    "IYC": "https://www.ishares.com/us/products/239740/ishares-us-consumer-discretionary-etf/1467271812596.ajax?fileType=csv&fileName=IYC_holdings&dataType=fund",
    "IYK": "https://www.ishares.com/us/products/239741/ishares-us-consumer-staples-etf/1467271812596.ajax?fileType=csv&fileName=IYK_holdings&dataType=fund",
    "IYJ": "https://www.ishares.com/us/products/239746/ishares-us-industrials-etf/1467271812596.ajax?fileType=csv&fileName=IYJ_holdings&dataType=fund",
    "IYM": "https://www.ishares.com/us/products/239752/ishares-us-basic-materials-etf/1467271812596.ajax?fileType=csv&fileName=IYM_holdings&dataType=fund",
    "IYR": "https://www.ishares.com/us/products/239812/ishares-us-real-estate-etf/1467271812596.ajax?fileType=csv&fileName=IYR_holdings&dataType=fund",
    "IDU": "https://www.ishares.com/us/products/239755/ishares-us-utilities-etf/1467271812596.ajax?fileType=csv&fileName=IDU_holdings&dataType=fund",
}

ISHARES_URLS_EU = {
    "EZU":  "https://www.ishares.com/us/products/239639/ishares-msci-eurozone-etf/1467271812596.ajax?fileType=csv&fileName=EZU_holdings&dataType=fund",
    "EWG":  "https://www.ishares.com/us/products/239629/ishares-msci-germany-etf/1467271812596.ajax?fileType=csv&fileName=EWG_holdings&dataType=fund",
    "EWQ":  "https://www.ishares.com/us/products/239641/ishares-msci-france-etf/1467271812596.ajax?fileType=csv&fileName=EWQ_holdings&dataType=fund",
    "EWU":  "https://www.ishares.com/us/products/239658/ishares-msci-united-kingdom-etf/1467271812596.ajax?fileType=csv&fileName=EWU_holdings&dataType=fund",
    "EWI":  "https://www.ishares.com/us/products/239637/ishares-msci-italy-etf/1467271812596.ajax?fileType=csv&fileName=EWI_holdings&dataType=fund",
    "EWP":  "https://www.ishares.com/us/products/239643/ishares-msci-spain-etf/1467271812596.ajax?fileType=csv&fileName=EWP_holdings&dataType=fund",
    "EWN":  "https://www.ishares.com/us/products/239640/ishares-msci-netherlands-etf/1467271812596.ajax?fileType=csv&fileName=EWN_holdings&dataType=fund",
    "EWK":  "https://www.ishares.com/us/products/239623/ishares-msci-belgium-etf/1467271812596.ajax?fileType=csv&fileName=EWK_holdings&dataType=fund",
    "EWD":  "https://www.ishares.com/us/products/239626/ishares-msci-sweden-etf/1467271812596.ajax?fileType=csv&fileName=EWD_holdings&dataType=fund",
    "EPOL": "https://www.ishares.com/us/products/239685/ishares-msci-poland-etf/1467271812596.ajax?fileType=csv&fileName=EPOL_holdings&dataType=fund",
    "EWL":  "https://www.ishares.com/us/products/239659/ishares-msci-switzerland-etf/1467271812596.ajax?fileType=csv&fileName=EWL_holdings&dataType=fund",
    "EWO":  "https://www.ishares.com/us/products/239622/ishares-msci-austria-etf/1467271812596.ajax?fileType=csv&fileName=EWO_holdings&dataType=fund",
}

ISHARES_URLS_ASIA = {
    "EWJ":  "https://www.ishares.com/us/products/239634/ishares-msci-japan-etf/1467271812596.ajax?fileType=csv&fileName=EWJ_holdings&dataType=fund",
    "EWY":  "https://www.ishares.com/us/products/239655/ishares-msci-south-korea-etf/1467271812596.ajax?fileType=csv&fileName=EWY_holdings&dataType=fund",
    "EWT":  "https://www.ishares.com/us/products/239657/ishares-msci-taiwan-etf/1467271812596.ajax?fileType=csv&fileName=EWT_holdings&dataType=fund",
    "EWH":  "https://www.ishares.com/us/products/239630/ishares-msci-hong-kong-etf/1467271812596.ajax?fileType=csv&fileName=EWH_holdings&dataType=fund",
    "EWA":  "https://www.ishares.com/us/products/239619/ishares-msci-australia-etf/1467271812596.ajax?fileType=csv&fileName=EWA_holdings&dataType=fund",
    "INDA": "https://www.ishares.com/us/products/268205/ishares-msci-india-etf/1467271812596.ajax?fileType=csv&fileName=INDA_holdings&dataType=fund",
    "EWZ":  "https://www.ishares.com/us/products/239612/ishares-msci-brazil-etf/1467271812596.ajax?fileType=csv&fileName=EWZ_holdings&dataType=fund",
    "EWC":  "https://www.ishares.com/us/products/239621/ishares-msci-canada-etf/1467271812596.ajax?fileType=csv&fileName=EWC_holdings&dataType=fund",
    "EWS":  "https://www.ishares.com/us/products/239649/ishares-msci-singapore-etf/1467271812596.ajax?fileType=csv&fileName=EWS_holdings&dataType=fund",
    "EEM":  "https://www.ishares.com/us/products/269849/ishares-msci-emerging-markets-etf/1467271812596.ajax?fileType=csv&fileName=EEM_holdings&dataType=fund",
    "ACWI": "https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf/1467271812596.ajax?fileType=csv&fileName=ACWI_holdings&dataType=fund",
}

STATIC_TICKERS = {
    "GPW": ["PKN.WA","PKO.WA","PZU.WA","PEKAO.WA","KGHM.WA","LPP.WA","DNP.WA",
            "ALE.WA","CDR.WA","CPS.WA","JSW.WA","KRU.WA","MBK.WA","OPL.WA",
            "PCO.WA","PLY.WA","SPL.WA","TPE.WA","ZPC.WA","11B.WA","ACT.WA",
            "AMB.WA","ATT.WA","BHW.WA","BRS.WA","CAR.WA","CCC.WA","CEZ.WA",
            "ENA.WA","ENP.WA","EUR.WA","GPW.WA","GTC.WA","ING.WA","KTY.WA",
            "LTS.WA","MLK.WA","MOL.WA","MRC.WA","OAT.WA"],
}

# ── POBIERANIE TICKERÓW ───────────────────────────────────────────────────────

def fetch_ishares_group(etf_dict: dict, label: str) -> list[tuple[str,str]]:
    result, seen_local = [], set()
    for name, url in etf_dict.items():
        try:
            print(f"    {name} ...", end=" ", flush=True)
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                print(f"HTTP {r.status_code}")
                continue
            lines = r.text.splitlines()
            start = next((i for i, l in enumerate(lines) if "Ticker" in l and "Name" in l), 0)
            df = pd.read_csv(io.StringIO("\n".join(lines[start:])), on_bad_lines="skip")
            col = next((c for c in df.columns if "Ticker" in c), None)
            if col:
                batch = [str(t).strip() for t in df[col].dropna()
                         if str(t).strip() not in ("-", "", "nan")]
                added = sum(1 for t in batch if t not in seen_local and not seen_local.add(t))
                for t in batch:
                    if t not in seen_local:
                        seen_local.add(t)
                        result.append((t, label))
                print(f"{len([t for t in batch if t])} tickerów")
            else:
                print("brak kolumny Ticker")
        except Exception as e:
            print(f"błąd: {e}")
        time.sleep(0.3)
    return result


def build_ticker_list() -> list[tuple[str,str]]:
    result, seen = [], set()

    def add(batch):
        for t, ex in batch:
            if t not in seen:
                seen.add(t)
                result.append((t, ex))

    print("  [USA] iShares ETF...")
    add(fetch_ishares_group(ISHARES_URLS_US, "US"))
    print("  [EU] iShares ETF...")
    add(fetch_ishares_group(ISHARES_URLS_EU, "EU"))
    print("  [ASIA/EM] iShares ETF...")
    add(fetch_ishares_group(ISHARES_URLS_ASIA, "ASIA"))
    print("  [STATIC] GPW + uzupełnienie...")
    for exchange, tickers in STATIC_TICKERS.items():
        for t in tickers:
            if t not in seen:
                seen.add(t)
                result.append((t, exchange))

    print(f"\n  ✅ Łącznie unikalnych tickerów: {len(result)}")
    return result

# ── FUNDAMENTY ────────────────────────────────────────────────────────────────

def safe(val, default=0.0):
    try: return float(val) if val is not None and val == val else default
    except: return default


def ohlson_score(info: dict, fin: pd.DataFrame, cf: pd.DataFrame) -> float | None:
    try:
        ta  = max(safe(info.get("totalAssets"), 1), 1)
        tl  = safe(info.get("totalDebt")) + safe(info.get("totalCurrentLiabilities"))
        ca  = safe(info.get("totalCurrentAssets"))
        cl  = safe(info.get("totalCurrentLiabilities"))
        ni  = safe(info.get("netIncomeToCommon"))
        ocf = safe(info.get("operatingCashflow"))

        if not fin.empty and "Net Income" in fin.index:
            v = fin.loc["Net Income"].dropna()
            if len(v): ni = float(v.iloc[0])
        if not cf.empty and "Operating Cash Flow" in cf.index:
            v = cf.loc["Operating Cash Flow"].dropna()
            if len(v): ocf = float(v.iloc[0])

        x1 = math.log(ta / 1e6) if ta > 0 else 0
        x2 = tl / ta
        x3 = (ca - cl) / ta
        x4 = cl / max(ca, 1)
        x5 = 1 if tl > ta else 0
        x6 = ni / ta
        x7 = ocf / ta
        x8 = 1 if ni < 0 else 0

        score = -1.32 - 0.407*x1 + 6.03*x2 - 1.43*x3 + 0.076*x4 \
                - 1.72*x5 - 2.37*x6 - 1.83*x7 + 0.285*x8
        return round(100 / (1 + math.exp(-score)), 2)
    except:
        return None


def check_fundamentals(ticker: str) -> dict | None:
    try:
        tk   = yf.Ticker(ticker)
        info = tk.info or {}
        try: fin = tk.financials
        except: fin = pd.DataFrame()
        try: cf  = tk.cashflow
        except: cf = pd.DataFrame()

        reasons = []

        mktcap = safe(info.get("marketCap"))
        if mktcap < FILTERS["market_cap_min"]:
            reasons.append(f"cap={mktcap/1e9:.2f}B")

        price = safe(info.get("currentPrice") or info.get("regularMarketPrice"))
        if price < FILTERS["price_min"]:
            reasons.append(f"price={price:.2f}")

        eps = safe(info.get("trailingEps") or info.get("epsTrailingTwelveMonths"))
        if eps < FILTERS["eps_ttm_min"]:
            reasons.append(f"eps={eps:.2f}")

        ebitda   = safe(info.get("ebitda"))
        revenue  = safe(info.get("totalRevenue"), 1)
        ebitda_m = (ebitda / revenue * 100) if revenue > 0 else 0
        if ebitda_m < FILTERS["ebitda_margin_min"]:
            reasons.append(f"ebitda_m={ebitda_m:.1f}%")

        ni           = safe(info.get("netIncomeToCommon"))
        total_equity = safe(info.get("bookValue")) * safe(info.get("sharesOutstanding"), 1)
        total_debt   = safe(info.get("totalDebt"))
        inv_cap      = total_equity + total_debt
        roic         = (ni / inv_cap * 100) if inv_cap > 0 else 0
        if roic < FILTERS["roic_min"]:
            reasons.append(f"roic={roic:.1f}%")

        cash_ops = safe(info.get("operatingCashflow"))
        if cash_ops == 0 and not cf.empty and "Operating Cash Flow" in cf.index:
            v = cf.loc["Operating Cash Flow"].dropna()
            if len(v): cash_ops = float(v.iloc[0])
        if cash_ops < FILTERS["cash_ops_min"]:
            reasons.append(f"cash_ops={cash_ops/1e6:.1f}M")

        rev_growth = safe(info.get("revenueGrowth")) * 100
        if rev_growth == 0 and not fin.empty and "Total Revenue" in fin.index:
            v = fin.loc["Total Revenue"].dropna()
            if len(v) >= 2:
                r0, r1 = float(v.iloc[0]), float(v.iloc[1])
                rev_growth = ((r0 - r1) / abs(r1) * 100) if r1 != 0 else 0
        if rev_growth < FILTERS["revenue_growth_min"]:
            reasons.append(f"rev={rev_growth:.1f}%")

        eps_growth = safe(info.get("earningsGrowth")) * 100

        ohlson = ohlson_score(info, fin, cf)
        if ohlson is not None and ohlson > FILTERS["ohlson_max"]:
            reasons.append(f"ohlson={ohlson:.1f}%")

        if reasons:
            if DEBUG: print(f"    SKIP {ticker:14s}: {', '.join(reasons)}")
            return None

        return {
            "name":          info.get("longName") or info.get("shortName", ""),
            "sector":        info.get("sector", ""),
            "industry":      info.get("industry", ""),
            "country":       info.get("country", ""),
            "price":         round(price, 2),
            "market_cap":    int(mktcap),
            "eps":           round(eps, 4),
            "eps_growth":    round(eps_growth, 2),
            "ebitda_margin": round(ebitda_m, 2),
            "roic":          round(roic, 2),
            "cash_ops":      int(cash_ops),
            "rev_growth":    round(rev_growth, 2),
            "ohlson":        ohlson,
        }
    except Exception as e:
        if DEBUG: print(f"    ERR {ticker}: {e}")
        return None

# ── TRADINGVIEW EXPORT ────────────────────────────────────────────────────────

TV_MAP = {
    # Yahoo suffix → TradingView prefix
    ".DE": "XETR", ".PA": "EURONEXT", ".AS": "EURONEXT", ".BR": "EURONEXT",
    ".L":  "LSE",  ".SW": "SIX",      ".WA": "GPW",      ".T":  "TSE",
    ".HK": "HKEX", ".AX": "ASX",      ".TO": "TSX",      ".KS": "KRX",
    ".NS": "NSE",  ".BO": "BSE",      ".SI": "SGX",
}

def to_tv(symbol: str) -> str:
    for suffix, prefix in TV_MAP.items():
        if symbol.endswith(suffix):
            base = symbol[:-len(suffix)].replace("-", ".").replace("^", "")
            return f"{prefix}:{base}"
    # US ticker — bez sufiksu
    return symbol.replace("-", ".").replace("^", "")


def save_tv_watchlist(results: list[dict]):
    tv_tickers = [to_tv(r["symbol"]) for r in results]
    # Pełna lista
    (RESULTS_DIR / "tv_watchlist.txt").write_text(",".join(tv_tickers))
    # Podział na regiony
    for region in ["US", "EU", "ASIA", "GPW"]:
        subset = [to_tv(r["symbol"]) for r in results if r.get("exchange") == region]
        if subset:
            (RESULTS_DIR / f"tv_{region.lower()}.txt").write_text(",".join(subset))
    print(f"  ✅ TradingView: {len(tv_tickers)} tickerów → tv_watchlist.txt + 4 regionalne")

# ── HTML ──────────────────────────────────────────────────────────────────────

CSS = """<style>
:root{--bg:#0f1117;--bg2:#1a1f2e;--bg3:#1e2530;--text:#e2e8f0;--muted:#64748b;
      --border:#2d3748;--green:#22c55e;--blue:#60a5fa;--yellow:#fbbf24;--red:#f87171}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);padding:20px}
header{text-align:center;padding:32px 0 24px;border-bottom:1px solid var(--border);margin-bottom:28px}
header h1{font-size:1.8rem;font-weight:800}
header p{color:var(--muted);font-size:.88rem;margin-top:6px}
.stats{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;margin-bottom:24px}
.stat{background:var(--bg3);border-radius:10px;padding:12px 22px;text-align:center}
.stat-n{font-size:1.6rem;font-weight:800}
.stat-l{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-top:2px}
.green{color:var(--green)}.blue{color:var(--blue)}.yellow{color:var(--yellow)}
.fbox{background:var(--bg3);border-radius:10px;padding:14px 18px;margin-bottom:24px;
      font-size:.79rem;color:var(--muted);line-height:2}
.fbox strong{color:var(--text)}
.search-bar{margin-bottom:20px}
.search-bar input{width:100%;background:var(--bg3);border:1px solid var(--border);
  border-radius:8px;color:var(--text);padding:10px 14px;font-size:.9rem;outline:none}
.search-bar input:focus{border-color:var(--blue)}
.tabs{display:flex;gap:6px;margin-bottom:18px;flex-wrap:wrap}
.tab{background:var(--bg3);border:1px solid var(--border);border-radius:8px;
     padding:7px 16px;font-size:.8rem;cursor:pointer;color:var(--muted);transition:all .15s}
.tab.active,.tab:hover{background:var(--blue);color:#fff;border-color:var(--blue)}
table{width:100%;border-collapse:collapse;font-size:.81rem}
thead th{background:var(--bg3);padding:9px 10px;text-align:left;font-size:.68rem;
         text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
         border-bottom:1px solid var(--border);position:sticky;top:0;cursor:pointer}
thead th:hover{color:var(--text)}
thead th.sorted-asc::after{content:" ▲"}
thead th.sorted-desc::after{content:" ▼"}
tbody tr{border-bottom:1px solid var(--border)}
tbody tr:hover{background:var(--bg2)}
tbody td{padding:8px 10px}
.ticker{font-weight:800;font-size:.93rem}
.name{color:var(--muted);font-size:.75rem;white-space:nowrap;overflow:hidden;
      text-overflow:ellipsis;max-width:160px;display:block}
.num{font-variant-numeric:tabular-nums}
.pos{color:var(--green)}.neg{color:var(--red)}
.ex{font-size:.68rem;color:var(--muted);background:var(--bg3);
    border-radius:4px;padding:1px 6px;white-space:nowrap}
.sec-tag{font-size:.68rem;color:var(--muted)}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
#count{color:var(--muted);font-size:.8rem;margin-bottom:10px}
</style>"""

THEAD = """<thead><tr>
<th data-col="symbol">Spółka</th>
<th data-col="exchange">Region</th>
<th data-col="sector">Sektor</th>
<th data-col="country">Kraj</th>
<th data-col="price">Cena</th>
<th data-col="market_cap">Market Cap</th>
<th data-col="rev_growth">Rev Growth</th>
<th data-col="eps_growth">EPS Growth</th>
<th data-col="ebitda_margin">EBITDA M.</th>
<th data-col="roic">ROIC</th>
<th data-col="eps">EPS TTM</th>
<th data-col="ohlson">Ohlson</th>
</tr></thead>"""

def fmt_cap(v):
    if v >= 1e12: return f"${v/1e12:.1f}T"
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    return f"${v/1e6:.0f}M"

def pct(v):
    return f'<span class="{"pos" if v>=0 else "neg"}">{v:+.1f}%</span>'

def table_rows(items):
    if not items:
        return '<tr><td colspan="12" style="text-align:center;padding:24px;color:var(--muted)">Brak wyników</td></tr>'
    rows = []
    for r in items:
        ohlson = f"{r['ohlson']:.1f}%" if r.get("ohlson") is not None else "—"
        rows.append(
            f'<tr data-exchange="{r.get("exchange","")}" '
            f'data-sector="{r.get("sector","")}">'
            f'<td><span class="ticker">'
            f'<a href="https://finance.yahoo.com/quote/{r["symbol"]}" target="_blank">{r["symbol"]}</a>'
            f'</span><span class="name">{r.get("name","")}</span></td>'
            f'<td><span class="ex">{r.get("exchange","")}</span></td>'
            f'<td><span class="sec-tag">{r.get("sector","")[:22]}</span></td>'
            f'<td class="num">{r.get("country","")}</td>'
            f'<td class="num">${r.get("price",0):.2f}</td>'
            f'<td class="num">{fmt_cap(r.get("market_cap",0))}</td>'
            f'<td class="num">{pct(r.get("rev_growth",0))}</td>'
            f'<td class="num">{pct(r.get("eps_growth",0))}</td>'
            f'<td class="num">{r.get("ebitda_margin",0):.1f}%</td>'
            f'<td class="num">{r.get("roic",0):.1f}%</td>'
            f'<td class="num">{r.get("eps",0):.2f}</td>'
            f'<td class="num">{ohlson}</td>'
            f'</tr>'
        )
    return "\n".join(rows)


JS = """
<script>
const allRows = Array.from(document.querySelectorAll('tbody tr'));
let activeTab = 'all';
let sortCol = 'market_cap', sortDir = -1;
let searchVal = '';

const colIndex = {};
document.querySelectorAll('thead th').forEach((th,i) => {
  colIndex[th.dataset.col] = i;
  th.addEventListener('click', () => {
    if(sortCol === th.dataset.col) sortDir *= -1;
    else { sortCol = th.dataset.col; sortDir = -1; }
    document.querySelectorAll('thead th').forEach(t => t.classList.remove('sorted-asc','sorted-desc'));
    th.classList.add(sortDir === 1 ? 'sorted-asc' : 'sorted-desc');
    render();
  });
});

document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    activeTab = t.dataset.tab;
    render();
  });
});

document.getElementById('search').addEventListener('input', e => {
  searchVal = e.target.value.toLowerCase();
  render();
});

function cellVal(row, col) {
  const idx = colIndex[col];
  if(idx === undefined) return '';
  const td = row.cells[idx];
  const span = td.querySelector('.ticker') || td.querySelector('span') || td;
  return (span.textContent || td.textContent).trim();
}

function numVal(row, col) {
  const v = cellVal(row, col).replace(/[$,TBM%+]/g,'');
  const n = parseFloat(v);
  return isNaN(n) ? -Infinity : n;
}

function render() {
  let rows = allRows.filter(r => {
    if(activeTab !== 'all' && r.dataset.exchange !== activeTab) return false;
    if(searchVal) {
      const txt = r.textContent.toLowerCase();
      if(!txt.includes(searchVal)) return false;
    }
    return true;
  });

  const numCols = ['price','market_cap','rev_growth','eps_growth','ebitda_margin','roic','eps','ohlson'];
  rows.sort((a,b) => {
    const v = numCols.includes(sortCol)
      ? (numVal(a,sortCol) - numVal(b,sortCol)) * sortDir
      : cellVal(a,sortCol).localeCompare(cellVal(b,sortCol)) * sortDir;
    return v;
  });

  const tbody = document.querySelector('tbody');
  rows.forEach(r => tbody.appendChild(r));
  allRows.filter(r => !rows.includes(r)).forEach(r => r.style.display='none');
  rows.forEach(r => r.style.display='');
  document.getElementById('count').textContent = `Wyświetlono: ${rows.length} spółek`;
}

render();
</script>"""

def gen_screener(results: list[dict], ts: str) -> str:
    by_ex = {}
    for r in results:
        by_ex.setdefault(r.get("exchange","?"), []).append(r)

    tabs_html = '<div class="tabs">'
    tabs_html += f'<div class="tab active" data-tab="all">Wszystkie ({len(results)})</div>'
    for ex, items in sorted(by_ex.items(), key=lambda x: -len(x[1])):
        tabs_html += f'<div class="tab" data-tab="{ex}">{ex} ({len(items)})</div>'
    tabs_html += '</div>'

    fbox = f"""<div class="fbox">
<strong>Filtry fundamentalne:</strong>
MarketCap ≥ <strong>1B</strong> &nbsp;·&nbsp;
Cena ≥ <strong>$10</strong> &nbsp;·&nbsp;
EPS TTM ≥ <strong>0.10</strong> &nbsp;·&nbsp;
EBITDA Margin ≥ <strong>15%</strong> &nbsp;·&nbsp;
ROIC ≥ <strong>10%</strong> &nbsp;·&nbsp;
Rev Growth ≥ <strong>5% YoY</strong> &nbsp;·&nbsp;
Cash Ops ≥ <strong>$1M</strong> &nbsp;·&nbsp;
Ohlson Score ≤ <strong>5%</strong>
&nbsp;&nbsp;|&nbsp;&nbsp;
<strong>Bez filtru SMI</strong> — do samodzielnej analizy w TradingView
</div>"""

    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Global Fundamental Screener</title>{CSS}</head><body>
<header>
  <h1>🌍 Global Fundamental Screener</h1>
  <p>Filtry fundamentalne · yfinance · Bez SMI &nbsp;|&nbsp; {ts}</p>
</header>
<div class="stats">
  <div class="stat"><div class="stat-n green">{len([r for r in results if r.get("exchange")=="US"])}</div><div class="stat-l">🇺🇸 USA</div></div>
  <div class="stat"><div class="stat-n blue">{len([r for r in results if r.get("exchange")=="EU"])}</div><div class="stat-l">🇪🇺 Europa</div></div>
  <div class="stat"><div class="stat-n yellow">{len([r for r in results if r.get("exchange")=="ASIA"])}</div><div class="stat-l">🌏 Azja/EM</div></div>
  <div class="stat"><div class="stat-n">{len(results)}</div><div class="stat-l">Łącznie</div></div>
</div>
{fbox}
<div class="search-bar"><input id="search" type="text" placeholder="🔍  Szukaj po nazwie, tickerze, sektorze..."></div>
{tabs_html}
<div id="count"></div>
<table>{THEAD}<tbody>{table_rows(results)}</tbody></table>
{JS}
<footer style="text-align:center;color:var(--muted);font-size:.75rem;padding:40px 0 20px">
Dane: Yahoo Finance (yfinance) · Tylko informacyjne, nie stanowi rekomendacji inwestycyjnej
</footer></body></html>"""


def gen_index(results: list[dict], ts: str) -> str:
    us  = len([r for r in results if r.get("exchange")=="US"])
    eu  = len([r for r in results if r.get("exchange")=="EU"])
    asi = len([r for r in results if r.get("exchange")=="ASIA"])
    gpw = len([r for r in results if r.get("exchange")=="GPW"])
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Global Fundamental Screener</title>{CSS}
<style>
.hero{{text-align:center;padding:60px 20px}}
.hero h1{{font-size:2.2rem;font-weight:900;margin-bottom:8px}}
.hero p{{color:var(--muted);margin-bottom:36px}}
.cards{{display:flex;gap:16px;justify-content:center;flex-wrap:wrap;margin-bottom:40px}}
.card{{background:var(--bg3);border-radius:14px;padding:24px 32px;text-align:center;
       min-width:140px;border:1px solid var(--border);transition:transform .15s}}
.card:hover{{transform:translateY(-3px)}}
.card-n{{font-size:2rem;font-weight:900}}
.card-l{{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:4px}}
.btn{{display:inline-block;background:#3b82f6;color:#fff;border-radius:10px;
      padding:13px 30px;font-size:1rem;font-weight:700;text-decoration:none;margin:6px}}
.btn:hover{{background:#2563eb}}
.btn-sec{{background:var(--bg3);color:var(--text);border:1px solid var(--border)}}
.btn-sec:hover{{background:var(--bg2)}}
.ts{{color:var(--muted);font-size:.8rem;margin-top:16px}}
</style></head><body>
<div class="hero">
  <h1>🌍 Global Fundamental Screener</h1>
  <p>MarketCap ≥ 1B · EBITDA ≥ 15% · ROIC ≥ 10% · RevGrowth ≥ 5% · Ohlson ≤ 5%</p>
  <div class="cards">
    <div class="card"><div class="card-n green">{us}</div><div class="card-l">🇺🇸 USA</div></div>
    <div class="card"><div class="card-n blue">{eu}</div><div class="card-l">🇪🇺 Europa</div></div>
    <div class="card"><div class="card-n yellow">{asi}</div><div class="card-l">🌏 Azja/EM</div></div>
    <div class="card"><div class="card-n">{gpw}</div><div class="card-l">🇵🇱 GPW</div></div>
    <div class="card"><div class="card-n">{len(results)}</div><div class="card-l">Łącznie</div></div>
  </div>
  <a href="screener.html" class="btn">📊 Otwórz screener</a>
  <a href="tv_watchlist.txt" class="btn btn-sec">📺 TradingView lista</a>
  <div class="ts">Ostatnia aktualizacja: {ts}</div>
</div></body></html>"""

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n🌍 Global Fundamental Screener — {ts}")
    print(f"   DEBUG={'ON' if DEBUG else 'OFF'}")

    # ETAP 1: tickery
    print("\n═══ ETAP 1: Pobieranie tickerów ═══")
    all_tickers = build_ticker_list()

    # ETAP 2: fundamenty
    print(f"\n═══ ETAP 2: Weryfikacja fundamentalna ({len(all_tickers)} tickerów) ═══")
    results, skipped, errs = [], 0, 0
    total = len(all_tickers)

    for i, (ticker, exchange) in enumerate(all_tickers, 1):
        if i % 100 == 0 or i == total:
            print(f"  [{i}/{total}] ✅{len(results)} ❌{skipped} ⚠{errs}")

        try:
            fund = check_fundamentals(ticker)
            if fund is None:
                skipped += 1
            else:
                results.append({"symbol": ticker, "exchange": exchange, **fund})
                print(f"  ✅ {ticker:16s} | {fund['name'][:30]:30s} | "
                      f"Cap:{fund['market_cap']/1e9:.1f}B ROIC:{fund['roic']:.0f}%")
        except Exception as e:
            errs += 1
            if DEBUG: print(f"  ⚠️  {ticker}: {e}")
            time.sleep(0.5)

        time.sleep(0.15)

    # Sortuj malejąco po market cap
    results.sort(key=lambda r: -r.get("market_cap", 0))

    print(f"\n═══ PODSUMOWANIE ═══")
    print(f"  ✅ Przeszło filtry : {len(results)}")
    print(f"  ❌ Odfiltrowane    : {skipped}")
    print(f"  ⚠️  Błędy           : {errs}")
    print(f"  📊 Łącznie tickerów: {total}")

    # ETAP 3: zapis
    print("\n═══ ETAP 3: Zapis ═══")
    (RESULTS_DIR/"results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2))
    (RESULTS_DIR/"meta.json").write_text(json.dumps({
        "run_ts": ts, "total": len(results),
        "us":   len([r for r in results if r.get("exchange")=="US"]),
        "eu":   len([r for r in results if r.get("exchange")=="EU"]),
        "asia": len([r for r in results if r.get("exchange")=="ASIA"]),
        "gpw":  len([r for r in results if r.get("exchange")=="GPW"]),
        "tickers_checked": total, "filtered_out": skipped,
    }, indent=2))
    (RESULTS_DIR/"screener.html").write_text(gen_screener(results, ts))
    (RESULTS_DIR/"index.html").write_text(gen_index(results, ts))
    save_tv_watchlist(results)

    print(f"\n🏁 Gotowe — {len(results)} spółek spełnia filtry.")

if __name__ == "__main__":
    main()
