# 🌍 Global Stock Screener

Automatyczny screener akcji z globalnym zasięgiem — USA, Europa, Azja, EM.

## Jak działa

**Etap 1 — FMP Stock Screener API**  
Zawęża ~80 000 globalnych spółek do kandydatów spełniających twarde filtry:

| Filtr | Wartość |
|---|---|
| Market Cap | ≥ 10B USD |
| Cena | ≥ $10 |
| Revenue growth (2Y est.) | ≥ 5% |
| EPS growth (2Y est.) | ≥ 5% |
| EPS Basic TTM | ≥ 0,10 |
| EBITDA Margin TTM | ≥ 15% |
| ROIC TTM | ≥ 10% |
| Cash from Operations TTM | ≥ $1M |
| Ohlson Score | ≤ 3% (ryzyko bankructwa) |

**Etap 2 — yfinance + SMI(10,3,3) W1**  
Dla kandydatów sprawdza sygnał na interwale tygodniowym:
- ⚡ **STRONG BUY** — SMI crossover gdy SMI < −40 (strefa wyprzedania)
- ▲ **BUY** — SMI crossover
- ↗ **TURNING UP** — SMI zmienia kierunek w górę (przed crossover)

**Etap 3 — Raporty**  
Generuje `results/screener.html`, `results/index.html`, JSON oraz watchlisty TradingView.

## Struktura repozytorium

```
scripts/
  screener.py          # główny skrypt
.github/workflows/
  screener.yml         # cron: pon–pt 15:00 UTC (17:00 PL)
results/
  index.html           # landing page (GitHub Pages)
  screener.html        # pełny raport
  results.json         # dane JSON
  meta.json            # statystyki
  tv_strong.txt        # TradingView: Strong BUY
  tv_buy.txt           # TradingView: BUY
  tv_turning.txt       # TradingView: Turning Up
  tv_all.txt           # TradingView: wszystkie
requirements.txt
```

## Konfiguracja

### 1. Dodaj klucz FMP jako Secret w GitHub

`Settings → Secrets and variables → Actions → New repository secret`

- Name: `FMP_API_KEY`
- Value: Twój klucz z financialmodelingprep.com

### 2. Włącz GitHub Pages

`Settings → Pages → Source: GitHub Actions`

### 3. Pierwsze uruchomienie

`Actions → Global Stock Screener → Run workflow`

## Giełdy (pokrycie globalne)

USA: NASDAQ, NYSE, AMEX  
Europa: EURONEXT, LSE, XETRA  
Kanada: TSX · Australia: ASX  
Indie: NSE, BSE · Japonia: TSE  
Azja: HKEX, SGX, KRX  

## Lokalne uruchomienie

```bash
pip install -r requirements.txt
export FMP_API_KEY="twoj_klucz"
python scripts/screener.py
```

---
*Wyłącznie informacyjne. Nie stanowi rekomendacji inwestycyjnej.*
