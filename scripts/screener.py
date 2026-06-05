#!/usr/bin/env python3
"""
Global Stock Screener — yfinance only
======================================
Etap 1 : Pobiera listy tickerów z iShares ETF (USA) + statyczna lista EU/Azja
Etap 2 : yfinance — filtry fundamentalne (MarketCap, EPS, EBITDA, ROIC, growth)
Etap 3 : yfinance — SMI(10,3,3) W1 → sygnał
Etap 4 : HTML + JSON + TradingView export

Filtry (zgodnie z obrazkiem):
  Market Cap          ≥ 1B USD
  Price               ≥ 10
  EPS Basic TTM       ≥ 0.10
  EBITDA Margin TTM   ≥ 15%
  ROIC TTM            ≥ 10%
  Revenue growth YoY  ≥ 5%
  Cash from Ops TTM   ≥ 1 000 000
  Ohlson Score        ≤ 5%
"""

import os, json, time, math, requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

# ── KONFIGURACJA ──────────────────────────────────────────────────────────────
DEBUG = os.environ.get("DEBUG", "0") == "1"

FILTERS = dict(
    market_cap_min     = 1_000_000_000,   # 1B
    price_min          = 10.0,
    eps_ttm_min        = 0.10,
    ebitda_margin_min  = 15.0,            # %
    roic_min           = 10.0,            # %
    cash_ops_min       = 1_000_000,
    revenue_growth_min = 5.0,             # % YoY
    ohlson_max         = 5.0,             # %
)

SMI_K, SMI_D, SMI_SIG = 10, 3, 3
OVERSOLD = -40

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

# ── ŹRÓDŁA TICKERÓW ───────────────────────────────────────────────────────────

# iShares ETF holdings — USA (S&P500 + S&P600 + Russell 2000)
# iShares ETF — USA (~2500 spółek)
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

# iShares ETF — Europa
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
    "VGK":  "https://www.ishares.com/us/products/239639/ishares-msci-eurozone-etf/1467271812596.ajax?fileType=csv&fileName=EZU_holdings&dataType=fund",
}

# iShares ETF — Azja + reszta świata
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

# Połącz wszystkie
ISHARES_URLS = {**ISHARES_URLS_US, **ISHARES_URLS_EU, **ISHARES_URLS_ASIA}

# Europa + Azja — statyczna lista (tickery Yahoo Finance)
STATIC_TICKERS = {
    # Germany — DAX
    "XETRA": ["ADS.DE","AIR.DE","ALV.DE","BAS.DE","BAYN.DE","BMW.DE","CON.DE",
               "DAI.DE","DB1.DE","DBK.DE","DHL.DE","DTE.DE","EOAN.DE","FRE.DE",
               "HEI.DE","HEN3.DE","IFX.DE","MRK.DE","MUV2.DE","RWE.DE","SAP.DE",
               "SIE.DE","SHL.DE","VOW3.DE","VNA.DE","ZAL.DE","DPW.DE","ENR.DE",
               "FME.DE","MTX.DE","PAH3.DE","PUM.DE","QIA.DE","SDAX.DE","SRT.DE",
               "SY1.DE","TKA.DE","WDI.DE","1COV.DE","BOSS.DE"],
    # France — CAC40 + SBF120
    "EURONEXT_FR": ["AI.PA","AIR.PA","ALO.PA","ATO.PA","BN.PA","BNP.PA","CA.PA",
                    "CAP.PA","CS.PA","DG.PA","ENGI.PA","ERF.PA","GLE.PA","HO.PA",
                    "KER.PA","LR.PA","MC.PA","ML.PA","MT.PA","ORA.PA","PUB.PA",
                    "RI.PA","RMS.PA","RNO.PA","SAF.PA","SAN.PA","SGO.PA","STLAP.PA",
                    "SU.PA","SW.PA","TEC.PA","TTE.PA","UG.PA","VIE.PA","VIV.PA",
                    "WLN.PA","EL.PA","FP.PA","FTI.PA","ACA.PA"],
    # UK — FTSE100
    "LSE": ["AAL.L","ABF.L","ADM.L","AHT.L","ANTO.L","AV.L","AZN.L","BA.L",
            "BAB.L","BARC.L","BDEV.L","BKG.L","BLND.L","BP.L","BRBY.L","BT-A.L",
            "CCH.L","CNA.L","CPG.L","CRH.L","DCC.L","DGE.L","DLN.L","ECM.L",
            "EZJ.L","FERG.L","FLTR.L","GLEN.L","GSK.L","HIK.L","HL.L","HLMA.L",
            "HSBA.L","IAG.L","IHG.L","IMB.L","INF.L","ITRK.L","ITV.L","JD.L",
            "KGF.L","LAND.L","LGEN.L","LLOY.L","LSE.L","MCRO.L","MNDI.L","MNG.L",
            "MRO.L","NG.L","NWG.L","NXT.L","OCDO.L","PHNX.L","PRU.L","PSN.L",
            "PSON.L","RB.L","RDSA.L","REL.L","RIO.L","RKT.L","RMV.L","RR.L",
            "RS1.L","RSA.L","SBRY.L","SDR.L","SGE.L","SGRO.L","SKG.L","SMDS.L",
            "SMIN.L","SMT.L","SN.L","SPX.L","SSE.L","STAN.L","SVT.L","TSCO.L",
            "TW.L","ULVR.L","UU.L","VOD.L","WPP.L","WTB.L"],
    # Netherlands — AEX
    "EURONEXT_NL": ["AALB.AS","ABN.AS","ADYEN.AS","AGN.AS","AH.AS","AKZA.AS",
                    "ASM.AS","ASML.AS","ASR.AS","BESI.AS","DSM.AS","HEIA.AS",
                    "IMCD.AS","ING.AS","INGA.AS","KPN.AS","MT.AS","NN.AS",
                    "PHIA.AS","PRX.AS","RAND.AS","REN.AS","SHELL.AS","SBM.AS",
                    "UNA.AS","URW.AS","VPK.AS","WKL.AS"],
    # Switzerland — SMI
    "SIX": ["ABBN.SW","ALC.SW","CFR.SW","CSGN.SW","GEBN.SW","GIVN.SW","HOLN.SW",
            "KN.SW","LONN.SW","NESN.SW","NOVN.SW","PGHN.SW","ROCG.SW","ROG.SW",
            "SGSN.SW","SIKA.SW","SLHN.SW","SRENH.SW","UBSG.SW","ZURN.SW"],
    # Poland — WIG20 + mWIG40
    "GPW": ["PKN.WA","PKO.WA","PZU.WA","PEKAO.WA","KGHM.WA","LPP.WA","DNP.WA",
            "ALE.WA","CDR.WA","CPS.WA","JSW.WA","KRU.WA","MBK.WA","OPL.WA",
            "PCO.WA","PLY.WA","SPL.WA","TPE.WA","ZPC.WA","11B.WA","ACT.WA",
            "AMB.WA","ATT.WA","BHW.WA","BRS.WA","CAR.WA","CCC.WA","CEZ.WA",
            "ENA.WA","ENP.WA","EUR.WA","GPW.WA","GTC.WA","ING.WA","KTY.WA",
            "LTS.WA","MLK.WA","MOL.WA","MRC.WA","OAT.WA"],
    # Japan — Nikkei225 (wybrane)
    "TSE": ["7203.T","9984.T","6758.T","8306.T","9432.T","7267.T","6861.T",
            "4063.T","9433.T","8316.T","7974.T","6367.T","6501.T","6902.T",
            "4502.T","8035.T","6954.T","4523.T","2914.T","8411.T","9022.T",
            "9021.T","7011.T","4519.T","5108.T","6098.T","3382.T","8001.T",
            "8002.T","8031.T"],
    # Hong Kong — HSI (wybrane)
    "HKEX": ["0005.HK","0700.HK","0941.HK","1299.HK","0939.HK","1398.HK",
             "2318.HK","3988.HK","0388.HK","0883.HK","0002.HK","0003.HK",
             "0011.HK","1109.HK","0016.HK","0017.HK","0688.HK","0857.HK",
             "1088.HK","2628.HK"],
    # Australia — ASX200 (wybrane)
    "ASX": ["BHP.AX","CBA.AX","CSL.AX","ANZ.AX","WBC.AX","NAB.AX","WES.AX",
            "MQG.AX","RIO.AX","TLS.AX","WOW.AX","TCL.AX","STO.AX","AMC.AX",
            "REA.AX","COL.AX","ALL.AX","IAG.AX","QBE.AX","FMG.AX"],
    # Canada — TSX (wybrane)
    "TSX": ["RY.TO","TD.TO","BNS.TO","BMO.TO","CM.TO","CNR.TO","CP.TO",
            "ENB.TO","TRP.TO","SU.TO","ABX.TO","MFC.TO","SLF.TO","POW.TO",
            "BCE.TO","T.TO","CNQ.TO","CVE.TO","IMO.TO","FFH.TO"],
    # South Korea — KOSPI (wybrane)
    "KRX": ["005930.KS","000660.KS","035420.KS","005380.KS","051910.KS",
            "006400.KS","035720.KS","207940.KS","000270.KS","068270.KS"],
    # India — Nifty50 (wybrane, NSE)
    "NSE": ["RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
            "HINDUNILVR.NS","BAJFINANCE.NS","SBIN.NS","BHARTIARTL.NS","KOTAKBANK.NS",
            "LT.NS","ASIANPAINT.NS","AXISBANK.NS","MARUTI.NS","SUNPHARMA.NS",
            "TITAN.NS","ULTRACEMCO.NS","WIPRO.NS","POWERGRID.NS","NESTLEIND.NS"],
}


def fetch_ishares_group(etf_dict: dict, label: str) -> list[tuple[str, str]]:
    """Pobiera tickery z grupy iShares ETF. Zwraca listę (ticker, label)."""
    import io
    tickers = []
    seen_local = set()
    for name, url in etf_dict.items():
        try:
            print(f"    {name} ...", end=" ", flush=True)
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                print(f"HTTP {r.status_code}")
                continue
            lines = r.text.splitlines()
            start = 0
            for i, line in enumerate(lines):
                if "Ticker" in line and "Name" in line:
                    start = i
                    break
            df = pd.read_csv(
                io.StringIO("\n".join(lines[start:])),
                on_bad_lines="skip",
            )
            col = next((c for c in df.columns if "Ticker" in c), None)
            if col:
                batch = [str(t).strip() for t in df[col].dropna()
                         if str(t).strip() and str(t).strip() not in ("-","","nan")]
                added = 0
                for t in batch:
                    if t not in seen_local:
                        seen_local.add(t)
                        tickers.append((t, label))
                        added += 1
                print(f"{added} tickerów")
            else:
                print("brak kolumny Ticker")
        except Exception as e:
            print(f"błąd: {e}")
        time.sleep(0.3)
    return tickers


def build_ticker_list() -> list[tuple[str,str]]:
    """Zwraca listę (ticker, exchange/region). Deduplikuje globalnie."""
    result = []
    seen   = set()

    def add_batch(batch):
        for (t, ex) in batch:
            if t not in seen:
                seen.add(t)
                result.append((t, ex))

    # USA — iShares ETF sektorowe + indeksy (~5 000–7 000 unikalnych)
    print("  [USA] iShares ETF...")
    add_batch(fetch_ishares_group(ISHARES_URLS_US, "US"))

    # Europa — iShares ETF krajowe
    print("  [EU] iShares ETF...")
    add_batch(fetch_ishares_group(ISHARES_URLS_EU, "EU"))

    # Azja + reszta świata — iShares ETF
    print("  [ASIA/EM] iShares ETF...")
    add_batch(fetch_ishares_group(ISHARES_URLS_ASIA, "ASIA"))

    # Statyczna lista uzupełniająca (GPW + dodatkowe tickery)
    print("  [STATIC] Uzupełnienie statyczne...")
    for exchange, tickers in STATIC_TICKERS.items():
        for t in tickers:
            if t not in seen:
                seen.add(t)
                result.append((t, exchange))

    print(f"\n  ✅ Łącznie unikalnych tickerów: {len(result)}")
    return result


# ── FUNDAMENTY (yfinance) ─────────────────────────────────────────────────────

def safe(val, default=0.0):
    try: return float(val) if val is not None and val == val else default
    except: return default


def ohlson_score(info: dict, fin: pd.DataFrame, bs: pd.DataFrame, cf: pd.DataFrame) -> float | None:
    """Uproszczony Ohlson O-Score → prawdopodobieństwo bankructwa (%)."""
    try:
        ta   = safe(info.get("totalAssets"), 1)
        tl   = safe(info.get("totalDebt", 0)) + safe(info.get("totalCurrentLiabilities", 0))
        ca   = safe(info.get("totalCurrentAssets", 0))
        cl   = safe(info.get("totalCurrentLiabilities", 0))
        ni   = safe(info.get("netIncomeToCommon", 0))
        ocf  = safe(info.get("operatingCashflow", 0))

        # fallback z financial statements
        if not fin.empty and "Net Income" in fin.index:
            ni_vals = fin.loc["Net Income"].dropna()
            ni = float(ni_vals.iloc[0]) if len(ni_vals) > 0 else ni
        if not cf.empty and "Operating Cash Flow" in cf.index:
            ocf_vals = cf.loc["Operating Cash Flow"].dropna()
            ocf = float(ocf_vals.iloc[0]) if len(ocf_vals) > 0 else ocf

        ta   = max(ta, 1)
        x1   = math.log(ta / 1e6) if ta > 0 else 0
        x2   = tl / ta
        x3   = (ca - cl) / ta
        x4   = cl / max(ca, 1)
        x5   = 1 if tl > ta else 0
        x6   = ni / ta
        x7   = ocf / ta
        x8   = 1 if ni < 0 else 0
        x9   = 0  # uproszczenie (brak poprzedniego roku)

        score = (-1.32 - 0.407*x1 + 6.03*x2 - 1.43*x3 + 0.076*x4
                 - 1.72*x5 - 2.37*x6 - 1.83*x7 + 0.285*x8 - 0.521*x9)
        return round(100 / (1 + math.exp(-score)), 2)
    except:
        return None


def check_fundamentals(ticker: str) -> dict | None:
    """
    Pobiera dane z yfinance i weryfikuje wszystkie filtry.
    Zwraca dict z danymi lub None.
    """
    try:
        tk   = yf.Ticker(ticker)
        info = tk.info or {}

        # Pobierz sprawozdania finansowe
        try: fin = tk.financials
        except: fin = pd.DataFrame()
        try: bs  = tk.balance_sheet
        except: bs = pd.DataFrame()
        try: cf  = tk.cashflow
        except: cf = pd.DataFrame()

        reasons = []

        # ── Market Cap ──
        mktcap = safe(info.get("marketCap", 0))
        if mktcap < FILTERS["market_cap_min"]:
            reasons.append(f"mktcap={mktcap/1e9:.2f}B")

        # ── Cena ──
        price = safe(info.get("currentPrice") or info.get("regularMarketPrice", 0))
        if price < FILTERS["price_min"]:
            reasons.append(f"price={price:.2f}")

        # ── EPS TTM ──
        eps = safe(info.get("trailingEps") or info.get("epsTrailingTwelveMonths", 0))
        if eps < FILTERS["eps_ttm_min"]:
            reasons.append(f"eps={eps:.2f}")

        # ── EBITDA Margin ──
        ebitda        = safe(info.get("ebitda", 0))
        revenue       = safe(info.get("totalRevenue", 0))
        ebitda_margin = (ebitda / revenue * 100) if revenue > 0 else 0
        if ebitda_margin < FILTERS["ebitda_margin_min"]:
            reasons.append(f"ebitda_m={ebitda_margin:.1f}%")

        # ── ROIC ──
        net_income    = safe(info.get("netIncomeToCommon", 0))
        total_equity  = safe(info.get("bookValue", 0)) * safe(info.get("sharesOutstanding", 1))
        total_debt    = safe(info.get("totalDebt", 0))
        invested_cap  = total_equity + total_debt
        roic          = (net_income / invested_cap * 100) if invested_cap > 0 else 0
        if roic < FILTERS["roic_min"]:
            reasons.append(f"roic={roic:.1f}%")

        # ── Cash from Operations ──
        cash_ops = safe(info.get("operatingCashflow", 0))
        # fallback z cashflow statement
        if cash_ops == 0 and not cf.empty and "Operating Cash Flow" in cf.index:
            vals = cf.loc["Operating Cash Flow"].dropna()
            if len(vals) > 0:
                cash_ops = float(vals.iloc[0])
        if cash_ops < FILTERS["cash_ops_min"]:
            reasons.append(f"cash_ops={cash_ops/1e6:.1f}M")

        # ── Revenue Growth YoY ──
        rev_growth = safe(info.get("revenueGrowth", 0)) * 100
        # fallback z financial statements
        if rev_growth == 0 and not fin.empty and "Total Revenue" in fin.index:
            rev_vals = fin.loc["Total Revenue"].dropna()
            if len(rev_vals) >= 2:
                r0, r1 = float(rev_vals.iloc[0]), float(rev_vals.iloc[1])
                rev_growth = ((r0 - r1) / abs(r1) * 100) if r1 != 0 else 0
        if rev_growth < FILTERS["revenue_growth_min"]:
            reasons.append(f"rev_growth={rev_growth:.1f}%")

        # ── EPS Growth (dla info) ──
        eps_growth = safe(info.get("earningsGrowth", 0)) * 100

        # ── Ohlson Score ──
        ohlson = ohlson_score(info, fin, bs, cf)
        if ohlson is not None and ohlson > FILTERS["ohlson_max"]:
            reasons.append(f"ohlson={ohlson:.1f}%")

        if reasons:
            if DEBUG:
                print(f"    SKIP {ticker:12s}: {', '.join(reasons)}")
            return None

        return {
            "name":          info.get("longName") or info.get("shortName", ""),
            "sector":        info.get("sector", ""),
            "price":         round(price, 2),
            "market_cap":    int(mktcap),
            "eps":           round(eps, 4),
            "ebitda_margin": round(ebitda_margin, 2),
            "roic":          round(roic, 2),
            "cash_ops":      int(cash_ops),
            "rev_growth":    round(rev_growth, 2),
            "eps_growth":    round(eps_growth, 2),
            "ohlson":        ohlson,
        }

    except Exception as e:
        if DEBUG:
            print(f"    ERR {ticker}: {e}")
        return None


# ── SMI ───────────────────────────────────────────────────────────────────────

def calc_smi(close: pd.Series, k=10, d=3, sig=3):
    ll   = close.rolling(k).min()
    hh   = close.rolling(k).max()
    ds   = (close - (hh+ll)/2).ewm(span=d, adjust=False).mean()
    dds  = ds.ewm(span=d, adjust=False).mean()
    dif2 = (hh-ll).ewm(span=d, adjust=False).mean().ewm(span=d, adjust=False).mean()
    smi_s = pd.Series(np.where(dif2!=0, 100*dds/(0.5*dif2), 0), index=close.index)
    return smi_s, smi_s.ewm(span=sig, adjust=False).mean()


def get_smi_signal(ticker: str):
    try:
        hist = yf.Ticker(ticker).history(period="2y", interval="1wk", auto_adjust=True)
        if hist.empty or len(hist) < 25:
            return None, 0.0, 0.0
        smi_s, sig_s = calc_smi(hist["Close"])
        s0,s1,s2 = smi_s.iloc[-1], smi_s.iloc[-2], smi_s.iloc[-3]
        e0,e1    = sig_s.iloc[-1], sig_s.iloc[-2]

        if   s1<=e1 and s0>e0 and s1<OVERSOLD: return "STRONG BUY", round(float(s0),2), round(float(e0),2)
        elif s1<=e1 and s0>e0:                  return "BUY",        round(float(s0),2), round(float(e0),2)
        elif s0>s1 and s1<=s2 and s0<e0:        return "TURNING UP", round(float(s0),2), round(float(e0),2)
        return None, 0.0, 0.0
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
.stat-n{font-size:1.6rem;font-weight:800}.stat-l{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-top:2px}
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
.ticker{font-weight:800;font-size:.93rem}.name{color:var(--muted);font-size:.76rem}
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

def pct(v):
    return f'<span class="{"pos" if v>=0 else "neg"}">{v:+.1f}%</span>'

THEAD = """<thead><tr>
<th>Spółka</th><th>Sygnał</th><th>Giełda</th><th>Sektor</th><th>Cena</th>
<th>Market Cap</th><th>Rev Growth</th><th>EPS Growth</th><th>EBITDA M.</th>
<th>ROIC</th><th>EPS TTM</th><th>Ohlson</th><th>SMI/Sig</th>
</tr></thead>"""

def table_rows(items):
    if not items:
        return '<tr><td colspan="13" style="text-align:center;padding:24px;color:var(--muted)">Brak wyników</td></tr>'
    rows = []
    for r in items:
        ohlson = f"{r['ohlson']:.1f}%" if r.get("ohlson") is not None else "—"
        rows.append(f"""<tr>
<td><span class="ticker"><a href="https://finance.yahoo.com/quote/{r['symbol']}" target="_blank">{r['symbol']}</a></span>
    <br><span class="name">{str(r.get('name',''))[:28]}</span></td>
<td>{badge(r['signal'])}</td>
<td><span class="ex">{r.get('exchange','')}</span></td>
<td><span class="name">{str(r.get('sector',''))[:20]}</span></td>
<td class="num">${r.get('price',0):.2f}</td>
<td class="num">{fmt_cap(r.get('market_cap',0))}</td>
<td class="num">{pct(r.get('rev_growth',0))}</td>
<td class="num">{pct(r.get('eps_growth',0))}</td>
<td class="num">{r.get('ebitda_margin',0):.1f}%</td>
<td class="num">{r.get('roic',0):.1f}%</td>
<td class="num">{r.get('eps',0):.2f}</td>
<td class="num">{ohlson}</td>
<td class="num">{r.get('smi_val',0):.1f}/{r.get('smi_sig',0):.1f}</td>
</tr>""")
    return "\n".join(rows)

def gen_screener(results, ts):
    strong  = [r for r in results if r["signal"]=="STRONG BUY"]
    buy     = [r for r in results if r["signal"]=="BUY"]
    turning = [r for r in results if r["signal"]=="TURNING UP"]
    fbox = f"""<div class="fbox">
<strong>Filtry:</strong> MarketCap≥<strong>1B</strong> · Cena≥<strong>$10</strong> ·
EPS≥<strong>0.10</strong> · EBITDA M.≥<strong>15%</strong> · ROIC≥<strong>10%</strong> ·
RevGrowth≥<strong>5%</strong> · CashOps≥<strong>$1M</strong> · Ohlson≤<strong>5%</strong> ·
<strong>SMI(10,3,3) W1</strong>
</div>"""
    def sec(title, color, items):
        return f'<section><h2 class="{color}">{title}</h2><table>{THEAD}<tbody>{table_rows(items)}</tbody></table></section>'
    return f"""<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Global Stock Screener</title>{CSS}</head><body>
<header><h1>🌍 Global Stock Screener</h1>
<p>SMI(10,3,3) · Tygodniowy · yfinance · {ts}</p></header>
<div class="stats">
<div class="stat"><div class="stat-n green">{len(strong)}</div><div class="stat-l">⚡ Strong BUY</div></div>
<div class="stat"><div class="stat-n blue">{len(buy)}</div><div class="stat-l">▲ BUY</div></div>
<div class="stat"><div class="stat-n purple">{len(turning)}</div><div class="stat-l">↗ Turning Up</div></div>
<div class="stat"><div class="stat-n">{len(results)}</div><div class="stat-l">Łącznie</div></div>
</div>{fbox}
{sec("⚡ Strong BUY — crossover z oversold (SMI &lt; −40)","green",strong)}
{sec("▲ BUY — SMI crossover","blue",buy)}
{sec("↗ Turning Up — zmiana kierunku (pre-crossover)","purple",turning)}
<footer style="text-align:center;color:var(--muted);font-size:.75rem;padding:40px 0 20px">
Dane: Yahoo Finance (yfinance) · Tylko informacyjne, nie stanowi rekomendacji
</footer></body></html>"""

def gen_index(results, ts):
    s=len([r for r in results if r["signal"]=="STRONG BUY"])
    b=len([r for r in results if r["signal"]=="BUY"])
    t=len([r for r in results if r["signal"]=="TURNING UP"])
    return f"""<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Global Screener</title>{CSS}
<style>
.hero{{text-align:center;padding:70px 20px}}
.hero h1{{font-size:2.4rem;font-weight:900;margin-bottom:10px}}
.hero p{{color:var(--muted);margin-bottom:40px}}
.cards{{display:flex;gap:18px;justify-content:center;flex-wrap:wrap;margin-bottom:44px}}
.card{{background:var(--bg3);border-radius:14px;padding:28px 36px;text-align:center;min-width:150px;border:1px solid var(--border);transition:transform .15s}}
.card:hover{{transform:translateY(-3px)}}
.card-n{{font-size:2.2rem;font-weight:900}}
.card-l{{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:4px}}
.btn{{display:inline-block;background:#3b82f6;color:#fff;border-radius:10px;padding:14px 32px;font-size:1rem;font-weight:700;text-decoration:none}}
.btn:hover{{background:#2563eb}}
.ts{{color:var(--muted);font-size:.8rem;margin-top:18px}}
</style></head><body>
<div class="hero"><h1>🌍 Global Stock Screener</h1>
<p>SMI(10,3,3) · Tygodniowy · Filtry fundamentalne · yfinance</p>
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
def save_tv(results):
    groups = {"strong":[],"buy":[],"turning":[],"all":[]}
    EX = {"XETRA":"XETR","EURONEXT_FR":"EURONEXT","EURONEXT_NL":"EURONEXT",
          "LSE":"LSE","SIX":"SIX","GPW":"GPW","TSE":"TSE","HKEX":"HKEX",
          "ASX":"ASX","TSX":"TSX","KRX":"KRX","NSE":"NSE","US":""}
    for r in results:
        sym = r["symbol"]
        ex  = r.get("exchange","")
        pfx = EX.get(ex, ex)
        base = sym.replace("-",".").split(".")[0]
        tv_sym = f"{pfx}:{base}" if pfx else base
        groups["all"].append(tv_sym)
        if   r["signal"]=="STRONG BUY": groups["strong"].append(tv_sym)
        elif r["signal"]=="BUY":        groups["buy"].append(tv_sym)
        else:                           groups["turning"].append(tv_sym)
    for name, tickers in groups.items():
        (RESULTS_DIR/f"tv_{name}.txt").write_text(",".join(tickers))
    print(f"  ✅ TV watchlists: {len(groups['all'])} tickerów")

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n🌍 Global Stock Screener — {ts}")
    print(f"   DEBUG={'ON' if DEBUG else 'OFF'}")
    print(f"   Filtry: {FILTERS}")

    # ETAP 1: budowanie listy tickerów
    print("\n═══ ETAP 1: Lista tickerów ═══")
    all_tickers = build_ticker_list()

    # ETAP 2+3: fundamenty + SMI
    print(f"\n═══ ETAP 2+3: Fundamenty + SMI ({len(all_tickers)} tickerów) ═══")
    results, skipped, no_sig, errs = [], 0, 0, 0
    total = len(all_tickers)

    for i, (ticker, exchange) in enumerate(all_tickers, 1):
        if i % 50 == 0 or i == total:
            print(f"  [{i}/{total}] ✅{len(results)} ❌{skipped} 〰{no_sig} ⚠{errs}")

        try:
            fund = check_fundamentals(ticker)
            if fund is None:
                skipped += 1
                time.sleep(0.15)
                continue

            sig, smi_v, smi_sv = get_smi_signal(ticker)
            if sig is None:
                no_sig += 1
                if DEBUG:
                    print(f"    NO_SIG {ticker}")
                time.sleep(0.2)
                continue

            results.append({
                "symbol":   ticker,
                "exchange": exchange,
                "signal":   sig,
                "smi_val":  smi_v,
                "smi_sig":  smi_sv,
                **fund,
            })
            print(f"  ✅ {ticker:14s} | {sig:12s} | SMI {smi_v:+.1f}")
            time.sleep(0.4)

        except Exception as e:
            errs += 1
            if DEBUG:
                print(f"  ⚠️  {ticker}: {e}")
            time.sleep(0.5)

        time.sleep(0.1)

    # sortowanie
    order = {"STRONG BUY":0,"BUY":1,"TURNING UP":2}
    results.sort(key=lambda r: (order.get(r["signal"],9), -r.get("market_cap",0)))

    strong_n  = sum(1 for r in results if r["signal"]=="STRONG BUY")
    buy_n     = sum(1 for r in results if r["signal"]=="BUY")
    turning_n = sum(1 for r in results if r["signal"]=="TURNING UP")

    print(f"\n═══ PODSUMOWANIE ═══")
    print(f"  ⚡ STRONG BUY : {strong_n}")
    print(f"  ▲  BUY       : {buy_n}")
    print(f"  ↗  TURNING UP: {turning_n}")
    print(f"  ❌ Odfiltrowane: {skipped}/{total}")
    print(f"  〰  Bez sygnału : {no_sig}")
    print(f"  ⚠️  Błędy       : {errs}")

    # ETAP 4: zapis
    print("\n═══ ETAP 4: Zapis ═══")
    (RESULTS_DIR/"results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
    (RESULTS_DIR/"meta.json").write_text(json.dumps({
        "run_ts":ts,"total":len(results),"strong":strong_n,"buy":buy_n,"turning":turning_n,
        "tickers_checked":total,"filtered_out":skipped,"no_signal":no_sig,
    },indent=2))
    (RESULTS_DIR/"screener.html").write_text(gen_screener(results,ts))
    (RESULTS_DIR/"index.html").write_text(gen_index(results,ts))
    save_tv(results)
    print(f"\n🏁 Gotowe — {len(results)} sygnałów.")

if __name__ == "__main__":
    main()
