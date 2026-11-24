# Data sources and terms

Janus is local-first and does not redistribute market data. Every adapter is a
client; the user is responsible for the terms of the source they configure.

## Default free stack

| Source | Data | Access | Terms / notes |
| --- | --- | --- | --- |
| Tiingo | EOD prices, news | API key | Free tier is rate-limited; do not redistribute |
| yfinance | Yahoo Finance prices | Unofficial, no key | Delayed/unofficial; fallback only; respect Yahoo's terms |
| SEC EDGAR | Filings, XBRL facts | Public, no key | Set a descriptive `User-Agent`; 10 req/s; public domain |
| FRED / ALFRED | Macro series, vintages | API key | Attribution: Federal Reserve Bank of St. Louis |
| GDELT | Global news events | Public, no key | Noisy; attribution to the GDELT Project |
| RSS / IR | Company and publisher feeds | Public | Respect robots.txt and publisher terms |

## Rules

1. **Do not commit or redistribute licensed data.** Tests use small, synthetic
   or public fixtures only.
2. **Cache politely.** The adapters use a local cache and rate limits; do not
   remove them.
3. **Preserve provenance.** Every observation stores `source`, `raw_hash`, and
   `raw_uri` when available.
4. **Point-in-time, not latest.** Use as-filed facts and ALFRED vintages for
   historical views.
5. **No scraping behind a paywall or login.** Do not add adapters that bypass
   access controls.
6. **No investment advice.** Janus is research tooling; it does not recommend
   buys or sells and does not promise returns.

## Attribution

When you publish research that uses these sources, cite the source and the
access date. The project itself ships no data.
