#!/usr/bin/env python3
"""
Global Fundamental Screener
=============================
Źródła tickerów:
  USA  : Wikipedia (S&P500, S&P400, S&P600) + NASDAQ/NYSE listed companies
  EU   : statyczna lista ~500 spółek (DAX, CAC, FTSE, AEX, SMI, MIB, IBEX, OMX, GPW...)
  Azja : statyczna lista ~200 spółek (Nikkei, KOSPI, HSI, ASX, Nifty...)

Filtry fundamentalne (bez SMI):
  Market Cap  ≥ 200M
  Price       ≥ 5
  EPS TTM     > 0
  EBITDA M.   ≥ 15%
  ROIC        ≥ 10%
  Rev Growth  ≥ 5% YoY (lub skip gdy brak danych)
  Cash Ops    ≥ 100 000
  Ohlson      ≤ 10%
"""

import os, json, time, math, io, requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

DEBUG       = os.environ.get("DEBUG", "0") == "1"
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

FILTERS = dict(
    market_cap_min     = 200_000_000,
    price_min          = 5.0,
    eps_ttm_min        = 0.01,
    ebitda_margin_min  = 15.0,
    roic_min           = 10.0,
    cash_ops_min       = 100_000,
    revenue_growth_min = 5.0,
    ohlson_max         = 10.0,
)

# ── STATYCZNE LISTY TICKERÓW ──────────────────────────────────────────────────

EU_TICKERS = [
    # Germany DAX40
    "ADS.DE","AIR.DE","ALV.DE","BAS.DE","BAYN.DE","BMW.DE","BNR.DE","CON.DE",
    "1COV.DE","DHER.DE","DHL.DE","DTE.DE","EOAN.DE","FRE.DE","HEI.DE","HEN3.DE",
    "IFX.DE","MBG.DE","MRK.DE","MTX.DE","MUV2.DE","PAH3.DE","PUMA.DE","RHM.DE",
    "RWE.DE","SAP.DE","SIE.DE","SHL.DE","SY1.DE","VNA.DE","VOW3.DE","ZAL.DE",
    "DBK.DE","DPW.DE","ENR.DE","BOSS.DE","QIA.DE","TKA.DE","SDAX.DE",
    # MDAX wybrane
    "AFX.DE","BC8.DE","CBKG.DE","CWC.DE","EVD.DE","HAB.DE","HLE.DE","HOT.DE",
    "KGX.DE","LEG.DE","NDA.DE","O2D.DE","PNE.DE","PSM.DE","RRTL.DE","S92.DE",
    "SDM.DE","SGL.DE","SW6.DE","UTDI.DE","WAF.DE","WCH.DE","XONA.DE",
    # France CAC40 + SBF120
    "AI.PA","AIR.PA","ALO.PA","ATO.PA","BN.PA","BNP.PA","CA.PA","CAP.PA",
    "CS.PA","DG.PA","ENGI.PA","ERF.PA","GLE.PA","HO.PA","KER.PA","LR.PA",
    "MC.PA","ML.PA","ORA.PA","PUB.PA","RI.PA","RMS.PA","RNO.PA","SAF.PA",
    "SAN.PA","SGO.PA","SU.PA","TEC.PA","TTE.PA","UG.PA","VIE.PA","VIV.PA",
    "WLN.PA","EL.PA","FP.PA","ACA.PA","NK.PA","SW.PA","STLAP.PA","LI.PA",
    "ALSTOM.PA","AMUN.PA","DSY.PA","FNAC.PA","GTT.PA","HRS.PA","OREP.PA",
    # UK FTSE100
    "AAL.L","ABF.L","ADM.L","AHT.L","ANTO.L","AV.L","AZN.L","BA.L",
    "BARC.L","BDEV.L","BKG.L","BP.L","BRBY.L","BT-A.L","CCH.L","CNA.L",
    "CPG.L","CRH.L","DCC.L","DGE.L","EZJ.L","FERG.L","FLTR.L","GLEN.L",
    "GSK.L","HIK.L","HL.L","HLMA.L","HSBA.L","IAG.L","IHG.L","IMB.L",
    "ITRK.L","JD.L","KGF.L","LGEN.L","LLOY.L","LSE.L","MCRO.L","MNDI.L",
    "MNG.L","MRO.L","NG.L","NWG.L","NXT.L","PHNX.L","PRU.L","PSN.L",
    "PSON.L","REL.L","RIO.L","RKT.L","RMV.L","RR.L","RS1.L","SBRY.L",
    "SGE.L","SGRO.L","SMT.L","SN.L","SSE.L","STAN.L","SVT.L","TSCO.L",
    "TW.L","ULVR.L","UU.L","VOD.L","WPP.L","WTB.L","AUTO.L","EXPN.L",
    "III.L","INF.L","ITV.L","LAND.L","SPX.L","OCDO.L",
    # Netherlands AEX
    "AALB.AS","ABN.AS","ADYEN.AS","AGN.AS","AKZA.AS","ASM.AS","ASML.AS",
    "ASR.AS","BESI.AS","DSM.AS","HEIA.AS","IMCD.AS","ING.AS","KPN.AS",
    "NN.AS","PHIA.AS","PRX.AS","RAND.AS","SHELL.AS","UNA.AS","WKL.AS",
    "SBMO.AS","TKWY.AS","VPK.AS","URW.AS",
    # Switzerland SMI
    "ABBN.SW","ALC.SW","CFR.SW","GEBN.SW","GIVN.SW","HOLN.SW","KN.SW",
    "LONN.SW","NESN.SW","NOVN.SW","PGHN.SW","ROG.SW","SGSN.SW","SIKA.SW",
    "SLHN.SW","SRENH.SW","UBSG.SW","ZURN.SW","TEMN.SW","VACN.SW",
    # Italy FTSE MIB
    "A2A.MI","AMP.MI","ATL.MI","AZM.MI","BMED.MI","BPE.MI","BPER.MI",
    "CPR.MI","CNHI.MI","DIA.MI","ENEL.MI","ENI.MI","EXO.MI","FCA.MI",
    "G.MI","ISP.MI","ITT.MI","LDO.MI","MB.MI","MONC.MI","NEXI.MI",
    "PIRC.MI","PRY.MI","PST.MI","REC.MI","SPM.MI","SRG.MI","STM.MI",
    "TEN.MI","TIT.MI","TRN.MI","UCG.MI","UNI.MI",
    # Spain IBEX35
    "ACS.MC","ACX.MC","AMS.MC","ANA.MC","BBVA.MC","BKT.MC","CABK.MC",
    "CIE.MC","COL.MC","ELE.MC","ENG.MC","FER.MC","GRF.MC","IAG.MC",
    "IBE.MC","IDR.MC","ITX.MC","LOG.MC","MAP.MC","MEL.MC","MTS.MC",
    "NTGY.MC","PHM.MC","RED.MC","REP.MC","ROVI.MC","SAB.MC","SAN.MC",
    "SGRE.MC","SLR.MC","SOL.MC","TEF.MC","VIS.MC","CLNX.MC","AENA.MC",
    # Sweden OMX30
    "ALFA.ST","ASSA-B.ST","AZN.ST","BOL.ST","EKTA-B.ST","ERIC-B.ST",
    "ESSITY-B.ST","GETI-B.ST","HEXA-B.ST","HM-B.ST","HUSQ-B.ST","INVE-B.ST",
    "KINV-B.ST","LATO-B.ST","LUND-B.ST","NDA-SE.ST","NIBE-B.ST","SAND.ST",
    "SCA-B.ST","SEB-A.ST","SECU-B.ST","SHB-A.ST","SKA-B.ST","SKF-B.ST",
    "SSAB-A.ST","STE-R.ST","SWED-A.ST","TEL2-B.ST","TELIA.ST","VOLV-B.ST",
    # Denmark OMX C25
    "AMBU-B.CO","CARL-B.CO","CHR.CO","COLO-B.CO","DEMANT.CO","DSV.CO",
    "FLS.CO","GN.CO","ISS.CO","JYSK.CO","MAERSK-B.CO","NKT.CO","NZYM-B.CO",
    "ORSTED.CO","PNDORA.CO","RBREW.CO","ROC.CO","SIM.CO","TRYG.CO","VWS.CO",
    # Finland OMX Helsinki
    "FORTUM.HE","KEMIRA.HE","KNEBV.HE","METSO.HE","NESTE.HE","NOKIA.HE",
    "ORNBV.HE","OUT1V.HE","SAMPO.HE","STERV.HE","TEM1V.HE","UPM.HE","WRT1V.HE",
    # Norway OBX
    "AKRBP.OL","AKER.OL","AKSO.OL","BOUVET.OL","DNB.OL","EQNR.OL","FRO.OL",
    "MOWI.OL","NHY.OL","NSKOG.OL","ORKLA.OL","RECSI.OL","SALM.OL","SCHB.OL",
    "SRBNK.OL","STB.OL","TEL.OL","TOM.OL","ULTI.OL","YAR.OL",
    # Belgium BEL20
    "AB.BR","ABI.BR","ACKB.BR","AGS.BR","APAM.BR","ARGX.BR","BPOST.BR",
    "CFE.BR","COLR.BR","ELI.BR","ELIA.BR","GBLB.BR","GBL.BR","ING.BR",
    "KBC.BR","MELE.BR","PROX.BR","SOFINA.BR","SOLB.BR","UCB.BR","UMI.BR",
    # Austria ATX
    "AMS.VI","BG.VI","CAI.VI","EBS.VI","EVN.VI","FACC.VI","FLU.VI",
    "IIA.VI","OMV.VI","POST.VI","RBI.VI","SBO.VI","S.VI","TKA.VI",
    "UQA.VI","VER.VI","VIG.VI","VOE.VI","WIE.VI",
    # Poland WIG20 + mWIG40
    "PKN.WA","PKO.WA","PZU.WA","PKOBP.WA","KGHM.WA","LPP.WA","DNP.WA",
    "ALE.WA","CDR.WA","CPS.WA","JSW.WA","KRU.WA","MBK.WA","OPL.WA",
    "PCO.WA","SPL.WA","TPE.WA","11B.WA","ACT.WA","AMB.WA","ATT.WA",
    "BHW.WA","BRS.WA","GPW.WA","GTC.WA","INGBSK.WA","KTY.WA","LTS.WA",
    "MOL.WA","MRC.WA","OAT.WA","PEO.WA","PGE.WA","PKP.WA","PLW.WA",
    "SNK.WA","TEN.WA","VRG.WA","WIG.WA","XTB.WA",
    # Portugal PSI20
    "ALTR.LS","BCP.LS","COR.LS","CTT.LS","EDP.LS","EDPR.LS","EGL.LS",
    "GALP.LS","IBC.LS","JMT.LS","NOS.LS","NVG.LS","PHR.LS","RAM.LS",
    "RENE.LS","SEM.LS","SON.LS","SONAE.LS","THE.LS",
]

ASIA_TICKERS = [
    # Japan Nikkei225 wybrane
    "7203.T","9984.T","6758.T","8306.T","9432.T","7267.T","6861.T","4063.T",
    "9433.T","8316.T","7974.T","6367.T","6501.T","6902.T","4502.T","8035.T",
    "6954.T","4523.T","2914.T","8411.T","9022.T","9021.T","7011.T","4519.T",
    "5108.T","6098.T","3382.T","8001.T","8002.T","8031.T","4661.T","6594.T",
    "6762.T","6857.T","6920.T","7733.T","7832.T","8058.T","9735.T","9983.T",
    "2802.T","3659.T","4151.T","4452.T","4568.T","5401.T","6301.T","6326.T",
    "6471.T","6506.T","6645.T","6701.T","6702.T","6724.T","6752.T","6753.T",
    "6770.T","6841.T","6963.T","7013.T","7270.T","7272.T","7751.T","7752.T",
    "8253.T","8591.T","8601.T","8604.T","8630.T","8725.T","8750.T","8766.T",
    "8795.T","8802.T","9020.T","9064.T","9101.T","9107.T","9202.T","9503.T",
    # South Korea KOSPI
    "005930.KS","000660.KS","035420.KS","005380.KS","051910.KS","006400.KS",
    "035720.KS","207940.KS","000270.KS","068270.KS","105560.KS","055550.KS",
    "012330.KS","028260.KS","009830.KS","017670.KS","036570.KS","066570.KS",
    "251270.KS","326030.KS","034020.KS","047050.KS","003490.KS","009540.KS",
    "010950.KS","011200.KS","015760.KS","018880.KS","030200.KS","032830.KS",
    # Hong Kong HSI
    "0005.HK","0700.HK","0941.HK","1299.HK","0939.HK","1398.HK","2318.HK",
    "3988.HK","0388.HK","0883.HK","0002.HK","0003.HK","0011.HK","1109.HK",
    "0016.HK","0017.HK","0688.HK","0857.HK","1088.HK","2628.HK","0001.HK",
    "0012.HK","0027.HK","0066.HK","0101.HK","0151.HK","0175.HK","0267.HK",
    "0288.HK","0291.HK","0316.HK","0322.HK","0386.HK","0669.HK","0762.HK",
    "0823.HK","0836.HK","0868.HK","0916.HK","0960.HK","0968.HK","0992.HK",
    "1038.HK","1044.HK","1093.HK","1177.HK","1211.HK","1336.HK","1378.HK",
    "1833.HK","1876.HK","1928.HK","1997.HK","2007.HK","2020.HK","2382.HK",
    "2388.HK","2628.HK","3690.HK","3968.HK","6098.HK","6862.HK","9618.HK",
    "9988.HK","9999.HK",
    # Australia ASX200 wybrane
    "BHP.AX","CBA.AX","CSL.AX","ANZ.AX","WBC.AX","NAB.AX","WES.AX","MQG.AX",
    "RIO.AX","TLS.AX","WOW.AX","TCL.AX","STO.AX","AMC.AX","REA.AX","COL.AX",
    "ALL.AX","IAG.AX","QBE.AX","FMG.AX","APT.AX","APX.AX","ASX.AX","AZJ.AX",
    "BXB.AX","CAR.AX","CCP.AX","CPU.AX","CWY.AX","DXS.AX","GMG.AX","GPT.AX",
    "IEL.AX","JHX.AX","LLC.AX","MGR.AX","MIN.AX","MPL.AX","NCM.AX","NHF.AX",
    "NXT.AX","ORG.AX","ORI.AX","OZL.AX","PLS.AX","QAN.AX","RHC.AX","RMD.AX",
    "S32.AX","SCG.AX","SEK.AX","SGP.AX","SKI.AX","SHL.AX","SUN.AX","TAH.AX",
    "TPG.AX","TWE.AX","VCX.AX","VEA.AX","WHC.AX","WPL.AX","XRO.AX",
    # Canada TSX
    "RY.TO","TD.TO","BNS.TO","BMO.TO","CM.TO","CNR.TO","CP.TO","ENB.TO",
    "TRP.TO","SU.TO","ABX.TO","MFC.TO","SLF.TO","POW.TO","BCE.TO","T.TO",
    "CNQ.TO","CVE.TO","IMO.TO","FFH.TO","ATD.TO","BAM.TO","DOL.TO","EMA.TO",
    "FTS.TO","GIB-A.TO","L.TO","MG.TO","NTR.TO","OTEX.TO","PPL.TO","QSR.TO",
    "RCI-B.TO","SAP.TO","SHOP.TO","STN.TO","TRI.TO","WCN.TO","WSP.TO",
    # India Nifty50
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS","HINDUNILVR.NS",
    "BAJFINANCE.NS","SBIN.NS","BHARTIARTL.NS","KOTAKBANK.NS","LT.NS","ASIANPAINT.NS",
    "AXISBANK.NS","MARUTI.NS","SUNPHARMA.NS","TITAN.NS","ULTRACEMCO.NS","WIPRO.NS",
    "POWERGRID.NS","NESTLEIND.NS","HCLTECH.NS","TECHM.NS","INDUSINDBK.NS",
    "TATAMOTORS.NS","TATASTEEL.NS","JSWSTEEL.NS","ADANIENT.NS","ADANIPORTS.NS",
    "BAJAJ-AUTO.NS","BAJAJFINSV.NS","BPCL.NS","BRITANNIA.NS","CIPLA.NS",
    "COALINDIA.NS","DIVISLAB.NS","DRREDDY.NS","EICHERMOT.NS","GRASIM.NS",
    "HAVELLS.NS","HEROMOTOCO.NS","HINDALCO.NS","IOC.NS","ITC.NS","M&M.NS",
    "NTPC.NS","ONGC.NS","SBILIFE.NS","SHREECEM.NS","TATACONSUM.NS","UPL.NS",
    # Singapore STI
    "D05.SI","O39.SI","U11.SI","Z74.SI","C6L.SI","S68.SI","BN4.SI","C38U.SI",
    "G13.SI","H78.SI","J36.SI","J37.SI","N2IU.SI","S58.SI","U96.SI","V03.SI",
    "Y92.SI",
    # Taiwan TWSE wybrane
    "2330.TW","2317.TW","2454.TW","2303.TW","2308.TW","2382.TW","2412.TW",
    "2891.TW","2882.TW","2881.TW","2886.TW","1301.TW","1303.TW","2002.TW",
    "2207.TW","2357.TW","2395.TW","2408.TW","2474.TW","3008.TW","3711.TW",
    "4938.TW","6505.TW","6669.TW",
    # Brazil IBOV wybrane
    "PETR4.SA","VALE3.SA","ITUB4.SA","BBDC4.SA","ABEV3.SA","WEGE3.SA","RENT3.SA",
    "LREN3.SA","MGLU3.SA","RAIL3.SA","BBAS3.SA","BPAC11.SA","BRFS3.SA","CIEL3.SA",
    "CMIG4.SA","COGN3.SA","CPLE6.SA","CSAN3.SA","CSNA3.SA","ELET3.SA","EMBR3.SA",
    "ENBR3.SA","ENEV3.SA","ENGI11.SA","EQTL3.SA","FLRY3.SA","GGBR4.SA","GOAU4.SA",
    "HAPV3.SA","HYPE3.SA","IRBR3.SA","ITSA4.SA","JBSS3.SA","KLBN11.SA","MRFG3.SA",
    "MRVE3.SA","MULT3.SA","NTCO3.SA","PCAR3.SA","QUAL3.SA","RADL3.SA","RDOR3.SA",
    "SBSP3.SA","SLCE3.SA","SMLS3.SA","SUZB3.SA","TAEE11.SA","TIMP3.SA","TOTS3.SA",
    "UGPA3.SA","USIM5.SA","VIVT3.SA","YDUQ3.SA",
]

# ── POBIERANIE TICKERÓW USA Z WIKIPEDII ───────────────────────────────────────

def fetch_wikipedia_tickers() -> list[str]:
    """Pobiera listy tickerów z Wikipedii — S&P500, S&P400 MidCap, S&P600 SmallCap."""
    import io
    sources = {
        "S&P500":  "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "S&P400":  "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        "S&P600":  "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
    }
    tickers = []
    seen    = set()
    headers = {"User-Agent": "Mozilla/5.0 (screener-bot)"}

    for name, url in sources.items():
        try:
            print(f"    {name} (Wikipedia) ...", end=" ", flush=True)
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                print(f"HTTP {r.status_code}")
                continue
            tables = pd.read_html(io.StringIO(r.text))
            # znajdź tabelę z kolumną Symbol/Ticker
            found = False
            for df in tables:
                col = next((c for c in df.columns
                            if str(c).lower() in ("symbol","ticker","ticker symbol")), None)
                if col:
                    batch = [str(t).strip().replace(".","-")
                             for t in df[col].dropna()
                             if str(t).strip() not in ("", "nan")]
                    added = 0
                    for t in batch:
                        if t not in seen:
                            seen.add(t)
                            tickers.append(t)
                            added += 1
                    print(f"{added} tickerów")
                    found = True
                    break
            if not found:
                print("brak kolumny Symbol")
        except Exception as e:
            print(f"błąd: {e}")
        time.sleep(1)

    return tickers


def fetch_nasdaq_tickers() -> list[str]:
    """Pobiera wszystkie tickery notowane na NASDAQ i NYSE z NASDAQ API."""
    tickers = []
    seen    = set()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    }
    exchanges = ["nasdaq", "nyse", "amex"]
    for ex in exchanges:
        try:
            print(f"    NASDAQ API ({ex.upper()}) ...", end=" ", flush=True)
            url = (f"https://api.nasdaq.com/api/screener/stocks"
                   f"?tableonly=true&limit=5000&exchange={ex}&download=true")
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                print(f"HTTP {r.status_code}")
                continue
            data = r.json()
            rows = data.get("data", {}).get("rows", [])
            added = 0
            for row in rows:
                t = str(row.get("symbol","")).strip()
                if t and t not in seen and "/" not in t and "^" not in t:
                    seen.add(t)
                    tickers.append(t)
                    added += 1
            print(f"{added} tickerów")
        except Exception as e:
            print(f"błąd: {e}")
        time.sleep(1)
    return tickers


def build_ticker_list() -> list[tuple[str, str]]:
    """Zwraca listę (ticker, region). Deduplikuje globalnie."""
    result, seen = [], set()

    def add(batch, region):
        for t in batch:
            if t and t not in seen:
                seen.add(t)
                result.append((t, region))

    # USA — Wikipedia S&P500/400/600
    print("  [USA] Wikipedia S&P indeksy...")
    wiki = fetch_wikipedia_tickers()
    add(wiki, "US")

    # USA — uzupełnienie z NASDAQ API (pełna lista giełd)
    print("  [USA] NASDAQ/NYSE/AMEX pełna lista...")
    nasdaq = fetch_nasdaq_tickers()
    add(nasdaq, "US")

    # Europa — statyczna lista
    print(f"  [EU]  Statyczna lista ({len(EU_TICKERS)} tickerów)...")
    add(EU_TICKERS, "EU")

    # Azja + reszta świata — statyczna lista
    print(f"  [ASIA] Statyczna lista ({len(ASIA_TICKERS)} tickerów)...")
    add(ASIA_TICKERS, "ASIA")

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
        if not info or info.get("marketCap") is None:
            return None

        try: fin = tk.financials
        except: fin = pd.DataFrame()
        try: cf  = tk.cashflow
        except: cf = pd.DataFrame()

        reasons = []

        # ── Market Cap ──
        mktcap = safe(info.get("marketCap"))
        if mktcap < FILTERS["market_cap_min"]:
            reasons.append(f"cap={mktcap/1e6:.0f}M")

        # ── Cena ──
        price = safe(info.get("currentPrice") or info.get("regularMarketPrice"))
        if price < FILTERS["price_min"]:
            reasons.append(f"price={price:.2f}")

        # ── EPS TTM ──
        eps = safe(info.get("trailingEps") or info.get("epsTrailingTwelveMonths"))
        if eps < FILTERS["eps_ttm_min"]:
            reasons.append(f"eps={eps:.2f}")

        # ── EBITDA Margin ──
        ebitda  = safe(info.get("ebitda"))
        revenue = safe(info.get("totalRevenue"), 1)
        if ebitda == 0 and not fin.empty:
            for label in ["EBITDA", "Normalized EBITDA"]:
                if label in fin.index:
                    v = fin.loc[label].dropna()
                    if len(v): ebitda = float(v.iloc[0]); break
        if revenue <= 1 and not fin.empty:
            for label in ["Total Revenue", "Revenue"]:
                if label in fin.index:
                    v = fin.loc[label].dropna()
                    if len(v): revenue = max(float(v.iloc[0]), 1); break
        ebitda_m = (ebitda / revenue * 100) if revenue > 1 else 0
        if ebitda_m < FILTERS["ebitda_margin_min"]:
            reasons.append(f"ebitda_m={ebitda_m:.1f}%")

        # ── ROIC ──
        ni           = safe(info.get("netIncomeToCommon"))
        total_equity = safe(info.get("totalStockholdersEquity") or
                            info.get("stockholdersEquity"))
        if total_equity == 0:
            try:
                bs = tk.balance_sheet
                if not bs.empty:
                    for label in ["Stockholders Equity", "Total Equity Gross Minority Interest",
                                  "Common Stock Equity"]:
                        if label in bs.index:
                            v = bs.loc[label].dropna()
                            if len(v): total_equity = float(v.iloc[0]); break
            except: pass
        total_debt = safe(info.get("totalDebt"))
        inv_cap    = total_equity + total_debt
        roic       = (ni / inv_cap * 100) if inv_cap > 0 else 0
        if roic < FILTERS["roic_min"]:
            reasons.append(f"roic={roic:.1f}%")

        # ── Cash from Operations ──
        cash_ops = safe(info.get("operatingCashflow"))
        if cash_ops == 0 and not cf.empty:
            for label in ["Operating Cash Flow", "Cash From Operations"]:
                if label in cf.index:
                    v = cf.loc[label].dropna()
                    if len(v): cash_ops = float(v.iloc[0]); break
        if cash_ops < FILTERS["cash_ops_min"]:
            reasons.append(f"cash_ops={cash_ops/1e3:.0f}K")

        # ── Revenue Growth YoY ──
        rev_growth_raw = info.get("revenueGrowth")
        if rev_growth_raw is not None:
            rev_growth = float(rev_growth_raw) * 100
        else:
            rev_growth = None
            if not fin.empty:
                for label in ["Total Revenue", "Revenue"]:
                    if label in fin.index:
                        v = fin.loc[label].dropna()
                        if len(v) >= 2:
                            r0, r1 = float(v.iloc[0]), float(v.iloc[1])
                            rev_growth = ((r0 - r1) / abs(r1) * 100) if r1 != 0 else None
                        break
        if rev_growth is not None and rev_growth < FILTERS["revenue_growth_min"]:
            reasons.append(f"rev={rev_growth:.1f}%")

        eps_growth = safe(info.get("earningsGrowth")) * 100

        # ── Ohlson Score ──
        ohlson = ohlson_score(info, fin, cf)
        if ohlson is not None and ohlson > FILTERS["ohlson_max"]:
            reasons.append(f"ohlson={ohlson:.1f}%")

        if reasons:
            if DEBUG: print(f"    SKIP {ticker:16s}: {', '.join(reasons)}")
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
            "rev_growth":    round(rev_growth, 2) if rev_growth is not None else None,
            "ohlson":        ohlson,
        }
    except Exception as e:
        if DEBUG: print(f"    ERR {ticker}: {e}")
        return None

# ── TRADINGVIEW EXPORT ────────────────────────────────────────────────────────

TV_MAP = {
    ".DE":"XETR", ".PA":"EURONEXT", ".AS":"EURONEXT", ".BR":"EURONEXT",
    ".L":"LSE",   ".SW":"SIX",      ".WA":"GPW",      ".T":"TSE",
    ".HK":"HKEX", ".AX":"ASX",      ".TO":"TSX",      ".KS":"KRX",
    ".NS":"NSE",  ".BO":"BSE",      ".SI":"SGX",      ".TW":"TWSE",
    ".SA":"BOVESPA", ".ST":"OMX",   ".CO":"OMXCPH",   ".HE":"OMXHEX",
    ".OL":"OSL",  ".VI":"WBAG",     ".LS":"EURONEXT", ".MI":"MIL",
    ".MC":"BME",
}

def to_tv(symbol: str) -> str:
    for suffix, prefix in TV_MAP.items():
        if symbol.endswith(suffix):
            base = symbol[:-len(suffix)].replace("-",".")
            return f"{prefix}:{base}"
    return symbol.replace("-",".")


def save_tv_watchlist(results: list[dict]):
    tv_all = [to_tv(r["symbol"]) for r in results]
    (RESULTS_DIR / "tv_watchlist.txt").write_text(",".join(tv_all))
    for region in ["US","EU","ASIA","GPW"]:
        subset = [to_tv(r["symbol"]) for r in results if r.get("exchange")==region]
        if subset:
            (RESULTS_DIR / f"tv_{region.lower()}.txt").write_text(",".join(subset))
    print(f"  ✅ TradingView: {len(tv_all)} tickerów → tv_watchlist.txt + regionalne")

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
.fbox{background:var(--bg3);border-radius:10px;padding:14px 18px;margin-bottom:20px;
      font-size:.79rem;color:var(--muted);line-height:2}
.fbox strong{color:var(--text)}
.search-bar{margin-bottom:14px}
.search-bar input{width:100%;background:var(--bg3);border:1px solid var(--border);
  border-radius:8px;color:var(--text);padding:10px 14px;font-size:.9rem;outline:none}
.search-bar input:focus{border-color:var(--blue)}
.tabs{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}
.tab{background:var(--bg3);border:1px solid var(--border);border-radius:8px;
     padding:6px 14px;font-size:.78rem;cursor:pointer;color:var(--muted);transition:all .15s}
.tab.active,.tab:hover{background:var(--blue);color:#fff;border-color:var(--blue)}
table{width:100%;border-collapse:collapse;font-size:.81rem}
thead th{background:var(--bg3);padding:9px 10px;text-align:left;font-size:.68rem;
         text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
         border-bottom:1px solid var(--border);position:sticky;top:0;cursor:pointer;
         user-select:none}
thead th:hover{color:var(--text)}
thead th.asc::after{content:" ▲"}thead th.desc::after{content:" ▼"}
tbody tr{border-bottom:1px solid var(--border)}
tbody tr:hover{background:var(--bg2)}
tbody td{padding:8px 10px}
.ticker{font-weight:800;font-size:.93rem}
.nm{color:var(--muted);font-size:.74rem;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis;max-width:170px;display:block}
.num{font-variant-numeric:tabular-nums}
.pos{color:var(--green)}.neg{color:var(--red)}
.ex{font-size:.68rem;color:var(--muted);background:var(--bg3);
    border-radius:4px;padding:1px 6px}
.sec{font-size:.72rem;color:var(--muted)}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
#count{color:var(--muted);font-size:.8rem;margin-bottom:8px}
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
    if v>=1e12: return f"${v/1e12:.1f}T"
    if v>=1e9:  return f"${v/1e9:.1f}B"
    return f"${v/1e6:.0f}M"

def pct(v):
    if v is None: return '<span class="muted">—</span>'
    return f'<span class="{"pos" if v>=0 else "neg"}">{v:+.1f}%</span>'

def table_rows(items):
    if not items:
        return '<tr><td colspan="12" style="text-align:center;padding:24px;color:var(--muted)">Brak wyników</td></tr>'
    rows = []
    for r in items:
        ohlson = f"{r['ohlson']:.1f}%" if r.get("ohlson") is not None else "—"
        rows.append(
            f'<tr data-exchange="{r.get("exchange","")}">'
            f'<td><span class="ticker">'
            f'<a href="https://finance.yahoo.com/quote/{r["symbol"]}" target="_blank">{r["symbol"]}</a>'
            f'</span><span class="nm">{r.get("name","")}</span></td>'
            f'<td><span class="ex">{r.get("exchange","")}</span></td>'
            f'<td><span class="sec">{r.get("sector","")[:22]}</span></td>'
            f'<td class="num">{r.get("country","")}</td>'
            f'<td class="num">${r.get("price",0):.2f}</td>'
            f'<td class="num">{fmt_cap(r.get("market_cap",0))}</td>'
            f'<td class="num">{pct(r.get("rev_growth"))}</td>'
            f'<td class="num">{pct(r.get("eps_growth"))}</td>'
            f'<td class="num">{r.get("ebitda_margin",0):.1f}%</td>'
            f'<td class="num">{r.get("roic",0):.1f}%</td>'
            f'<td class="num">{r.get("eps",0):.2f}</td>'
            f'<td class="num">{ohlson}</td>'
            f'</tr>'
        )
    return "\n".join(rows)

JS = """<script>
const allRows=Array.from(document.querySelectorAll('tbody tr'));
let activeTab='all',sortCol='market_cap',sortDir=-1,searchVal='';
const colIdx={};
document.querySelectorAll('thead th').forEach((th,i)=>{
  colIdx[th.dataset.col]=i;
  th.addEventListener('click',()=>{
    if(sortCol===th.dataset.col)sortDir*=-1;
    else{sortCol=th.dataset.col;sortDir=-1;}
    document.querySelectorAll('thead th').forEach(t=>t.classList.remove('asc','desc'));
    th.classList.add(sortDir===1?'asc':'desc');
    render();
  });
});
document.querySelectorAll('.tab').forEach(t=>{
  t.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    t.classList.add('active');activeTab=t.dataset.tab;render();
  });
});
document.getElementById('search').addEventListener('input',e=>{searchVal=e.target.value.toLowerCase();render();});
function numVal(row,col){
  const idx=colIdx[col];if(idx===undefined)return -Infinity;
  const txt=(row.cells[idx].textContent||'').replace(/[$,TBMKb%+\s]/g,'');
  const n=parseFloat(txt);return isNaN(n)?-Infinity:n;
}
function txtVal(row,col){
  const idx=colIdx[col];if(idx===undefined)return'';
  return(row.cells[idx].textContent||'').trim();
}
function render(){
  const numCols=['price','market_cap','rev_growth','eps_growth','ebitda_margin','roic','eps','ohlson'];
  let rows=allRows.filter(r=>{
    if(activeTab!=='all'&&r.dataset.exchange!==activeTab)return false;
    if(searchVal&&!r.textContent.toLowerCase().includes(searchVal))return false;
    return true;
  });
  rows.sort((a,b)=>{
    const v=numCols.includes(sortCol)
      ?(numVal(a,sortCol)-numVal(b,sortCol))*sortDir
      :txtVal(a,sortCol).localeCompare(txtVal(b,sortCol))*sortDir;
    return v;
  });
  const tbody=document.querySelector('tbody');
  allRows.forEach(r=>r.style.display='none');
  rows.forEach(r=>{r.style.display='';tbody.appendChild(r);});
  document.getElementById('count').textContent=`Wyświetlono: ${rows.length} spółek`;
}
render();
</script>"""

def gen_screener(results, ts):
    by_ex = {}
    for r in results:
        by_ex.setdefault(r.get("exchange","?"),[]).append(r)
    tabs = '<div class="tabs">'
    tabs += f'<div class="tab active" data-tab="all">Wszystkie ({len(results)})</div>'
    for ex,items in sorted(by_ex.items(),key=lambda x:-len(x[1])):
        tabs += f'<div class="tab" data-tab="{ex}">{ex} ({len(items)})</div>'
    tabs += '</div>'

    fbox = f"""<div class="fbox">
<strong>Filtry:</strong> MarketCap≥<strong>200M</strong> · Cena≥<strong>$5</strong> ·
EPS&gt;<strong>0</strong> · EBITDA M.≥<strong>{FILTERS['ebitda_margin_min']}%</strong> ·
ROIC≥<strong>{FILTERS['roic_min']}%</strong> · RevGrowth≥<strong>{FILTERS['revenue_growth_min']}%</strong> ·
CashOps≥<strong>$100K</strong> · Ohlson≤<strong>{FILTERS['ohlson_max']}%</strong>
&nbsp;·&nbsp; <strong>Bez SMI</strong> — lista do analizy w TradingView
</div>"""

    us  = len([r for r in results if r.get("exchange")=="US"])
    eu  = len([r for r in results if r.get("exchange")=="EU"])
    asi = len([r for r in results if r.get("exchange")=="ASIA"])

    return f"""<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Global Fundamental Screener</title>{CSS}</head><body>
<header><h1>🌍 Global Fundamental Screener</h1>
<p>Filtry fundamentalne · yfinance · Bez SMI &nbsp;|&nbsp; {ts}</p></header>
<div class="stats">
<div class="stat"><div class="stat-n green">{us}</div><div class="stat-l">🇺🇸 USA</div></div>
<div class="stat"><div class="stat-n blue">{eu}</div><div class="stat-l">🇪🇺 Europa</div></div>
<div class="stat"><div class="stat-n yellow">{asi}</div><div class="stat-l">🌏 Azja/EM</div></div>
<div class="stat"><div class="stat-n">{len(results)}</div><div class="stat-l">Łącznie</div></div>
</div>
{fbox}
<div class="search-bar"><input id="search" type="text" placeholder="🔍  Szukaj po tickerze, nazwie, sektorze..."></div>
{tabs}
<div id="count"></div>
<table>{THEAD}<tbody>{table_rows(results)}</tbody></table>
{JS}
<footer style="text-align:center;color:var(--muted);font-size:.75rem;padding:40px 0 20px">
Dane: Yahoo Finance (yfinance) · Tylko informacyjne, nie stanowi rekomendacji inwestycyjnej
</footer></body></html>"""


def gen_index(results, ts):
    us  = len([r for r in results if r.get("exchange")=="US"])
    eu  = len([r for r in results if r.get("exchange")=="EU"])
    asi = len([r for r in results if r.get("exchange")=="ASIA"])
    return f"""<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
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
.btn2{{background:var(--bg3);color:var(--text);border:1px solid var(--border)}}
.btn2:hover{{background:var(--bg2)}}
.ts{{color:var(--muted);font-size:.8rem;margin-top:16px}}
</style></head><body>
<div class="hero">
<h1>🌍 Global Fundamental Screener</h1>
<p>MarketCap≥200M · EBITDA≥15% · ROIC≥10% · RevGrowth≥5% · Ohlson≤10%</p>
<div class="cards">
<div class="card"><div class="card-n green">{us}</div><div class="card-l">🇺🇸 USA</div></div>
<div class="card"><div class="card-n blue">{eu}</div><div class="card-l">🇪🇺 Europa</div></div>
<div class="card"><div class="card-n yellow">{asi}</div><div class="card-l">🌏 Azja/EM</div></div>
<div class="card"><div class="card-n">{len(results)}</div><div class="card-l">Łącznie</div></div>
</div>
<a href="screener.html" class="btn">📊 Otwórz screener</a>
<a href="tv_watchlist.txt" class="btn btn2">📺 TradingView lista</a>
<div class="ts">Ostatnia aktualizacja: {ts}</div>
</div></body></html>"""

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n🌍 Global Fundamental Screener — {ts}")
    print(f"   DEBUG={'ON' if DEBUG else 'OFF'}")

    print("\n═══ ETAP 1: Pobieranie tickerów ═══")
    all_tickers = build_ticker_list()

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
                print(f"  ✅ {ticker:16s} | {fund['name'][:28]:28s} | "
                      f"Cap:{fund['market_cap']/1e9:.1f}B ROIC:{fund['roic']:.0f}%")
        except Exception as e:
            errs += 1
            if DEBUG: print(f"  ⚠️  {ticker}: {e}")
            time.sleep(0.5)
        time.sleep(0.15)

    results.sort(key=lambda r: -r.get("market_cap", 0))

    print(f"\n═══ PODSUMOWANIE ═══")
    print(f"  ✅ Przeszło filtry : {len(results)}")
    print(f"  ❌ Odfiltrowane    : {skipped}")
    print(f"  ⚠️  Błędy           : {errs}")
    print(f"  📊 Sprawdzonych    : {total}")

    print("\n═══ ETAP 3: Zapis ═══")
    (RESULTS_DIR/"results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
    (RESULTS_DIR/"meta.json").write_text(json.dumps({
        "run_ts":ts,"total":len(results),
        "us":  len([r for r in results if r.get("exchange")=="US"]),
        "eu":  len([r for r in results if r.get("exchange")=="EU"]),
        "asia":len([r for r in results if r.get("exchange")=="ASIA"]),
        "tickers_checked":total,"filtered_out":skipped,
    },indent=2))
    (RESULTS_DIR/"screener.html").write_text(gen_screener(results,ts))
    (RESULTS_DIR/"index.html").write_text(gen_index(results,ts))
    save_tv_watchlist(results)
    print(f"\n🏁 Gotowe — {len(results)} spółek spełnia filtry.")

if __name__ == "__main__":
    main()
