# Tender Intel Daily

This folder now contains two layers:

- `build_tender_dashboard.py`
  Turns your historical workbook into a polished static dashboard so we can inspect old deal patterns.
- `daily_tender_digest.py`
  Builds the daily production pipeline for public-source tender monitoring, premium site output, and optional email delivery.

## What the daily pipeline does

- Queries public procurement sources with business keywords
- Preserves the original source URL for every notice
- Scores each notice into `High`, `Medium`, or `Watch`
- Labels opportunities as `Direct`, `Adjacent`, or `Monitor`
- Writes a premium static site to `docs`
- Writes a sales-ready CSV lead sheet
- Optionally sends the top opportunities by email
- Optionally upgrades copy with Gemini if `GEMINI_API_KEY` is provided
- Ships a Chinese-first, English-toggle website for leadership and sales teams
- Surfaces coverage metrics and source health so missed-source risk is visible

## Public-source strategy

The first production version is wired for these public sources:

- China Government Procurement search
- National Public Resource Trading Platform search

Recommended next sources to add after this base is stable:

- Electronic Tendering and Bidding Public Service Platform
- Public tender pages from tobacco system entities
- Provincial and municipal public resource platforms

The source backlog is tracked in [source-catalog.json](/C:/Users/user/Documents/New%20project/tender-intel-daily/source-catalog.json).
The latest validation notes are in [LIVE_VALIDATION_2026-03-23.md](/C:/Users/user/Documents/New%20project/tender-intel-daily/LIVE_VALIDATION_2026-03-23.md).

`source-catalog.json` now also holds `seed_sources`, which drive extra site-scoped Yahoo fallback discovery for tobacco-system entities and selected local public-resource portals.

Important compliance boundary:

- Good: monitor public pages, summarize, classify, dedupe, and keep source links
- Not recommended: bypass logins, member-only pages, CAPTCHAs, anti-bot controls, or paid walls

## Business keywords

The default keyword set covers:

- `文明吸烟环境`
- `吸烟室`
- `吸烟亭`
- `烟草公司`
- `移动公厕`
- `垃圾房`
- `集装箱厢房`

Update `SEARCH_KEYWORDS` in [daily_tender_digest.py](/C:/Users/user/Documents/New%20project/tender-intel-daily/daily_tender_digest.py) as your sales focus changes.

## Required dependencies

```powershell
pip install -r .\requirements.txt
```

## Local run: live public-source mode

```powershell
python .\daily_tender_digest.py
```

Useful environment variables:

- `LOOKBACK_DAYS`
- `SOURCE_PAGE_LIMIT`
- `MAX_ITEMS`
- `REQUEST_TIMEOUT_SECONDS`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `SEND_EMAIL`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `EMAIL_FROM` (optional, defaults to `SMTP_USERNAME`)
- `EMAIL_TO` (optional, defaults to `863370612lhy@gmail.com`)

## Local run: workbook demo mode

Use this when you want to test the whole output pipeline without making live web requests.

```powershell
$env:DEMO_WORKBOOK="D:\xwechat_files\wxid_kop5jjmasy0622_ecf0\msg\file\2026-03\文明吸烟环境招标信息汇总2023-2024年度(3).xlsx"
python .\tender-intel-daily\daily_tender_digest.py
```

Generated files:

- `docs/index.html`
- `docs/latest.json`
- `docs/sales-top.json`
- `docs/sales-leads.csv`

## Email delivery

Email is disabled by default.

Enable it with:

```powershell
$env:SEND_EMAIL="1"
$env:SMTP_USERNAME="your_email@gmail.com"
$env:SMTP_PASSWORD="your_app_password"
$env:EMAIL_TO="863370612lhy@gmail.com"
python .\daily_tender_digest.py
```

Gmail SMTP defaults are already built in:

- host: `smtp.gmail.com`
- port: `465`

The HTML email now has three sections:

- Sales priority leads
- Adjacent-space watchlist
- Source health diagnostics

The website now includes:

- Chinese-first UI with English toggle
- Search by title, region, keyword, priority, type, and source
- Coverage breadth cards showing official query count and seed-source count
- Source-health diagnostics so failures are visible instead of hidden

GitHub Actions is already pinned to send the digest to `863370612lhy@gmail.com`.
For cloud delivery, you now only need these repository secrets:

- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `GEMINI_API_KEY` (optional)

## Scheduler

Use the workflow in `.github/workflows/daily-tender-intel.yml` to run this every day on GitHub Actions.

For public sharing, `.github/workflows/deploy-tender-pages.yml` can deploy `docs` to GitHub Pages once the repo is pushed to GitHub.

## Local Windows auto-run

If you want daily delivery from this PC without GitHub, use:

- [run_daily_tender_intel.ps1](/C:/Users/user/Documents/New%20project/tender-intel-daily/run_daily_tender_intel.ps1)

It expects these user environment variables to exist:

- `SMTP_USERNAME`
- `SMTP_PASSWORD`

Every run writes a local execution log to:

- `logs/last-run.log`

The pipeline also writes daily historical snapshots into:

- `docs/archive/<report-date>/`
