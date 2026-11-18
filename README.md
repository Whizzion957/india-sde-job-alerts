# Role Atlas job search

Open **http://127.0.0.1:8765** on the Windows PC running Role Atlas. Choose **Sign in → Create an account** to save your preferences, track applications, and archive postings. You can browse without an account. The initial search uses India and one year of experience. Change either setting, pick role families, specify preferred skills, choose a work arrangement, or set a posting-date window in the dashboard.

Choose **Archive** on an irrelevant posting to remove it from Discover. Open **Archive** in the navigation to see or restore hidden postings. Search preferences also offer **Hide jobs I've applied to from Discover**. Archived postings and applications are saved with your account.

Choose **Save** to shortlist a role and return to it later. Marking it applied moves it to **Applications**, where **Update** lets you set the hiring stage, a follow-up date, and private notes. Use the tracker filters to see a stage, upcoming follow-ups, or follow-ups due today and earlier. Discover also surfaces a shortcut when a follow-up is due. Shortlist and application records retain a copy of the posting if it leaves the live feed.

### Coverage and matching

The dashboard collects open postings from Greenhouse, Ashby, Lever, Workday, Oracle Recruiting, SmartRecruiters, and employer-operated feeds. The **Company boards** view shows scope and scan status for each employer. Some feeds cover India and some cover global roles. Wipro uses recent public RSS results. Cisco and Postman provide listing summaries. IBM, Infosys, and TCS have direct career links while automated imports are unavailable.

Roles cover software, data science, data engineering, AI/ML, infrastructure, security, quality, hardware, technical operations and technical product/design. Multiple families can apply to a posting. Match details show the language used to infer minimum experience when it was found. A zero-year search excludes positive minimums and flags missing experience for review. Unchecking **Include opportunities with incomplete match information** limits that search to postings with explicit zero-experience evidence and other verified criteria. Preferred skills affect rank.

The scanner shares one catalog across accounts. It checks up to eight boards concurrently, publishes results board by board, and uses HTTP validators when available. Unchanged postings reuse classifications. A complete refresh removes closed roles. Partial refreshes can add verified postings while keeping prior results, and failed refreshes mark earlier results as stale. Marking a role as applied stores its details and application date in your account, including after the employer removes it.

### Running on Windows

The dashboard uses Python 3.12, Node.js 20 or newer, SQLite and public company APIs. It has no package-install step, external account requirement or hosted database. From the checkout, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\dashboard\install.ps1
```

The **India Tech Job Dashboard** task starts at Windows sign-in and listens on loopback. A board is due six hours after its last successful check. Failed or partial boards are eligible to retry after 30 minutes or the provider's longer retry delay. The scanner checks for due boards at startup and between passes while the PC is awake and the user is signed in. **Scan coverage** shows live progress, the most recent run's duration, and the next planned board check when idle. **Reload results** loads the latest collected postings. Each browser can sign into its own Role Atlas account on this PC. The database and rotating logs live under `dashboard/.state/` and are Git-ignored. Back up that directory with the task stopped to retain user records.

For foreground use, run `python -X utf8 dashboard/server.py` with the task stopped. Run the service tests with `python -m unittest discover -s dashboard/test` and the matching tests with `node --test dashboard/test/match.test.mjs`.

### Personal Telegram alerts

1. Create or sign into your Role Atlas account and save your search preferences. Start a private chat with your Telegram bot and send it a message such as `/start`.
2. Create `dashboard/.state/telegram.env` with the settings below. Use the token from BotFather and the private chat’s numeric `message.chat.id` from the bot’s `getUpdates` response. The configuration file is Git-ignored.

   ```dotenv
   TOKEN=your-bot-token
   CHAT_ID=your-private-chat-id
   ZERO_EXPERIENCE_ONLY=1
   ```

   For multiple Role Atlas accounts, set `USER_ID` to the intended account's `user.id` from `http://127.0.0.1:8765/api/session` while signed in. A single account is selected automatically.
3. With the dashboard running, alerts use the selected account's saved filters and the same **Why this matches** rules as Discover. `ZERO_EXPERIENCE_ONLY=1` requires an explicit zero-year minimum, including ranges such as **0–2 years**. Listings with missing experience or a review flag are skipped. Each qualifying posting is sent once to that chat. The worker checks for newly available results about every 90 seconds.

To preview the number of unsent matches without sending, run `python -X utf8 -m src.telegram_alerts --preview` from the `dashboard` directory.

## Original India entry-level SDE Telegram alerts

The separate Telegram scanner checks official company job boards for **new entry-level software roles in India**
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
| `run.ps1` | Windows Task Scheduler entry point. Writes a log per run to `logs/` and keeps 60 days. |

Personal and secret files are git-ignored: `telegram.env`, `applied.txt`, `seen.json`, `ALERTS.md`, `logs/`.

## Windows setup

Run these commands in PowerShell from the repo folder. Python 3 must be on your `PATH`.
You can check the job boards before configuring Telegram with `python -X utf8 alert_scan.py 7`.

1. If `telegram.env` does not exist, run `Copy-Item telegram.env.example telegram.env`.
   Open it with `notepad telegram.env` and set `TOKEN=` to the token from [@BotFather](https://t.me/BotFather).
2. Send your bot a message, then run `python -X utf8 notify.py --test`. This saves your chat ID and sends a test message.
3. Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1` for the first daily scan. Check `logs/` for the result.
4. In Task Scheduler, create a daily task at 9 PM IST using your Windows account. Set **Program/script** to `powershell.exe` and **Add arguments** to `-NoProfile -ExecutionPolicy Bypass -File "C:\path\to\india-sde-job-alerts\run.ps1"`, using your checkout's absolute path. Use 9 PM when Windows is set to India Standard Time.

To use a personal application list, copy `applied.txt.example` to `applied.txt` if it does not exist and replace the sample ID with your own.

## Linux setup

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
