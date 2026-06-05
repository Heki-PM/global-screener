#!/usr/bin/env python3
"""
Skrypt diagnostyczny — uruchom raz żeby zobaczyć co FMP zwraca.
Nie filtruje nic — pokazuje surowe dane dla 3 spółek.
"""
import os, json, requests

KEY = os.environ.get("FMP_API_KEY", "")
print(f"Klucz FMP: {KEY[:8]}...{KEY[-4:]} (długość: {len(KEY)})")
print("="*60)

def fmp(endpoint, params={}):
    r = requests.get(
        f"https://financialmodelingprep.com/api/v3/{endpoint}",
        params={"apikey": KEY, **params},
        timeout=20
    )
    print(f"  GET {endpoint} → HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  BODY: {r.text[:200]}")
        return None
    try:
        return r.json()
    except:
        print(f"  BODY (nie JSON): {r.text[:200]}")
        return None

# TEST 1: screener NASDAQ
print("\n[TEST 1] FMP /stock-screener NASDAQ marketCap>1B")
data = fmp("stock-screener", {
    "exchange": "NASDAQ",
    "marketCapMoreThan": 1_000_000_000,
    "priceMoreThan": 10,
    "isEtf": "false",
    "limit": 5,
})
if data and isinstance(data, list):
    print(f"  Wyników: {len(data)}")
    if data:
        print(f"  Pola dostępne: {list(data[0].keys())}")
        print(f"  Przykład: {json.dumps(data[0], indent=2)[:400]}")
        test_symbols = [d["symbol"] for d in data[:3]]
else:
    print(f"  Brak danych lub błąd")
    test_symbols = ["AAPL", "MSFT", "GOOGL"]

print(f"\n  Testowe symbole: {test_symbols}")

# TEST 2: income statement
print("\n[TEST 2] income-statement dla", test_symbols[0])
inc = fmp(f"income-statement/{test_symbols[0]}", {"limit": 2, "period": "annual"})
if inc and isinstance(inc, list) and inc:
    print(f"  Pola: {list(inc[0].keys())[:15]}")
    print(f"  revenue: {inc[0].get('revenue')}")
    print(f"  ebitda: {inc[0].get('ebitda')}")
    print(f"  netIncome: {inc[0].get('netIncome')}")
    print(f"  eps: {inc[0].get('eps')}")
    if len(inc) > 1:
        r0 = inc[0].get("revenue", 0) or 0
        r1 = inc[1].get("revenue", 1) or 1
        print(f"  rev growth: {(r0-r1)/abs(r1)*100:.1f}%")
else:
    print("  BRAK DANYCH")

# TEST 3: balance sheet
print("\n[TEST 3] balance-sheet dla", test_symbols[0])
bs = fmp(f"balance-sheet-statement/{test_symbols[0]}", {"limit": 2, "period": "annual"})
if bs and isinstance(bs, list) and bs:
    print(f"  totalAssets: {bs[0].get('totalAssets')}")
    print(f"  totalLiabilities: {bs[0].get('totalLiabilities')}")
    print(f"  totalStockholdersEquity: {bs[0].get('totalStockholdersEquity')}")
    print(f"  totalDebt: {bs[0].get('totalDebt')}")
else:
    print("  BRAK DANYCH")

# TEST 4: cash flow
print("\n[TEST 4] cash-flow dla", test_symbols[0])
cf = fmp(f"cash-flow-statement/{test_symbols[0]}", {"limit": 1, "period": "annual"})
if cf and isinstance(cf, list) and cf:
    print(f"  operatingCashFlow: {cf[0].get('operatingCashFlow')}")
else:
    print("  BRAK DANYCH")

# TEST 5: ratios-ttm
print("\n[TEST 5] ratios-ttm dla", test_symbols[0])
rat = fmp(f"ratios-ttm/{test_symbols[0]}")
if rat and isinstance(rat, list) and rat:
    print(f"  DOSTĘPNE na tym planie ✅")
    print(f"  ebitdaPerRevenueTTM: {rat[0].get('ebitdaPerRevenueTTM')}")
    print(f"  returnOnCapitalEmployedTTM: {rat[0].get('returnOnCapitalEmployedTTM')}")
else:
    print("  NIEDOSTĘPNE na tym planie ❌")

# TEST 6: API usage / limit
print("\n[TEST 6] sprawdzenie limitu API")
usage = requests.get(
    "https://financialmodelingprep.com/api/v4/usage",
    params={"apikey": KEY}, timeout=10
)
print(f"  HTTP {usage.status_code}: {usage.text[:200]}")

print("\n" + "="*60)
print("DIAGNOSTYKA ZAKOŃCZONA")
