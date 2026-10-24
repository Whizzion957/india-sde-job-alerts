# India entry-level SDE job alerts

A daily scanner that checks official company job boards for **new entry-level software roles in India**
and pushes only the postings it hasn't sent before to a Telegram bot.

No scraping of LinkedIn or Naukri, no API keys other than your own Telegram bot token, and no
third-party Python packages (it uses only the standard library).

## What it covers

| Source | Companies |
|---|---|
| Greenhouse | Graviton, Tower, AlphaGrep, Squarepoint, Rubrik, Databricks, Stripe, Coinbase, Cloudflare, Datadog, MongoDB, … |
| Lever / Ashby | CRED, Meesho, Zeta, Snowflake, Tekion, Sarvam, … |
| Workday | Salesforce, Adobe, NVIDIA, PayPal, Visa, Mastercard, Morgan Stanley, Accenture, Intel, … |
| Oracle HCM | Uber, JPMorgan, Oracle |
| Custom APIs | Microsoft, Google, Amazon, Atlassian, Apple |

Each posting is filtered to:
- India locations;
- software titles, excluding senior, staff, lead and test roles;
- at most 1 year of required experience (or an explicitly new-grad role).

Each one is tagged with a rough **fresher base-pay tier**: A ≥ ₹24L, B ₹18–24L, C likely < ₹18L, U unknown.
The tiers are estimates from public offer reports, not data from the postings themselves.

Meta can't be covered: metacareers.com blocks non-browser requests. Use Meta's own email job alerts instead.

## Files

| File | Purpose |
|---|---|
| `alert_scan.py` | Scanner. `python3 alert_scan.py 7` prints a markdown report of postings from the last 7 days; `--json` prints machine-readable output. |
| `notify.py` | Runs the scanner, keeps only unseen postings, sends them to Telegram, then records them in `seen.json` and `ALERTS.md`. Sends a short "no new postings" note on quiet days and a warning if the scan fails. |
| `run.sh` | Cron entry point; writes a log per run to `logs/` and keeps 60 days. |

Personal and secret files are git-ignored: `telegram.env`, `applied.txt`, `seen.json`, `ALERTS.md`, `logs/`.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Copy the example files and add the token:
   ```bash
   cp telegram.env.example telegram.env && chmod 600 telegram.env   # paste TOKEN=...
   cp applied.txt.example applied.txt                               # optional: IDs you've applied to
   ```
3. Send any message to your bot in Telegram, then run `python3 notify.py --test`.
   This saves your chat ID and sends a test message.
4. Optional: `python3 notify.py --preview` sends everything open in the last 30 days without recording it.
5. Schedule it daily. Cron uses UTC, so `30 15 * * *` is 9 PM IST:
   ```bash
   (crontab -l; echo "30 15 * * * $PWD/run.sh") | crontab -
   ```

A full scan takes about 7 minutes. If fewer than 10 job-board requests succeed (for example, the network is down),
the run reports **SCAN FAILED** instead of a false "no new postings".

## Customising

- **Skip roles you've applied to:** add the posting ID (any unique part of its URL) to `applied.txt`.
- **Never show a company:** add it to `EXCLUDE` in `alert_scan.py`.
- **Add companies:** add the board slug to `GH` / `LEVER` / `ASHBY`, or a `(tenant, wdN, site)` tuple to `WORKDAY`.
  Then set its pay tier in `TIER`.
