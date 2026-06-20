# Codex Usage

A local command-line tool for Codex users. It shows your reset credits, rate-limit windows, local usage metadata, read-only online usage/profile data, and optional report exports.

It is a single Python file. No package install. No API key.

## What it is good for

Use this script when you want to know:

- how many Codex rate-limit reset credits you have;
- when those reset credits expire, shown in your local timezone;
- whether your current Codex rate-limit windows are close to the limit;
- when the primary and weekly windows reset;
- what your local Codex usage metadata says about tokens, models, days, and heavy sessions;
- what Codex's read-only online usage/profile endpoints currently report;

## What it does

The script can show:

- a menu with a quick live summary;
- reset credits and expiry warnings;
- local usage counters from `~/.codex`;
- model and session summaries from local Codex metadata;
- daily local token totals;
- read-only online usage/profile information from ChatGPT/Codex backend endpoints;
- human-readable explanations for technical local files and online endpoint data;
- structured tables for reset credits, local SQLite/session metadata, daily usage, rate limits, credit events, profile stats, and exports;
- separate `Technical details` sections at the bottom of reports for endpoint paths, response shapes, and filtered raw fields;
- TXT, JSON, or CSV reports written beside the script;

## What it does not do

The script does **not**:

- redeem reset credits;
- buy credits;
- change your Codex or ChatGPT account;
- change Codex settings;
- upload local Codex transcripts;
- print prompts, assistant replies, commands, diffs, transcripts, or secrets;
- require an OpenAI API key;
- use the OpenAI API billing system;
- claim to be an official OpenAI or Codex tool.

The online endpoints used here are undocumented. They may change or disappear without notice.

## Requirements

- Python 3.10 or newer.
- A Codex login already present at `~/.codex/auth.json`.
- macOS or Linux. Windows is not supported.
- Network access only for reset credits and online usage/profile views.

No third-party Python packages are required.

### Windows support

Windows is not supported. The script expects Unix-style paths, an executable shebang workflow, and a Codex home at `~/.codex`. It is intended for macOS and Linux.

## Files

Expected repository layout:

```text
.gitignore
codex_usage.py
LICENCE
README.md
```

## Installation

From the directory containing `codex_usage.py`:

```sh
chmod +x codex_usage.py
./codex_usage.py
```

If you prefer not to mark the file executable, run it through Python instead:

```sh
python3 codex_usage.py
```

Optional syntax check before running:

```sh
python3 -m py_compile ./codex_usage.py
```

The syntax check only verifies that Python can parse the script. It does not contact Codex and does not read your account data.

## How the output is organised

Reports are designed for end users first:

1. each major section starts with a short explanation;
2. the main values are shown as readable tables with human labels;
3. endpoint paths, response shapes, and filtered raw fields are collected under `Technical details` near the bottom.

Use the main tables for normal reading. Use `Technical details` only when you want to verify exactly which backend endpoint or local source produced a value.

## Menu mode

In an interactive terminal, running the script without arguments opens the menu.

```sh
./codex_usage.py
```

The menu shows a quick summary first, then these choices:

```text
1) Show everything (resets + local + online)
2) Show reset credits only
3) Show local usage only (no network calls)
4) Show online usage/profile (GET only)
5) Export report
6) Settings (top=10, days=30, warn_days=7)
7) Refresh quick summary
q) Quit
```

## Direct commands

The README is the canonical place for help, privacy notes, limitations, and troubleshooting. The TUI keeps only operational menu actions.

You can use the menu, or call any report directly from the command line. Every command supports `-h` / `--help`; subcommands have their own help too, for example:

```sh
./codex_usage.py --help
./codex_usage.py local-usage --help
./codex_usage.py export --help
```

Show everything:

```sh
./codex_usage.py all
```

Show reset credits only:

```sh
./codex_usage.py resets
```

Warn if reset credits expire within 14 days:

```sh
./codex_usage.py resets --warn-days 14
```

Show local usage only. This makes no network calls:

```sh
./codex_usage.py local-usage
```

Show more local rows and more daily history:

```sh
./codex_usage.py local-usage --top 20 --days 60
```

Show online usage/profile data:

```sh
./codex_usage.py online-usage
```

Show online usage/profile data with fewer Technical details fields:

```sh
./codex_usage.py online-usage --top 3
```

Disable terminal colour. This is useful for logs, copied output, scripted checks, and plain-text captures:

```sh
./codex_usage.py local-usage --top 1 --days 1 --no-colour
./codex_usage.py online-usage --top 3 --no-colour
./codex_usage.py resets --no-colour
```

Print machine-readable JSON instead of prose and tables:

```sh
./codex_usage.py all --json
./codex_usage.py resets --json
./codex_usage.py local-usage --json
./codex_usage.py online-usage --json
```

Export a report:

```sh
./codex_usage.py export --report all --format txt
./codex_usage.py export --report all --format json
./codex_usage.py export --report all --format csv
```

Export only one report type:

```sh
./codex_usage.py export --report resets --format txt
./codex_usage.py export --report local-usage --format csv
./codex_usage.py export --report online-usage --format json
```

## Command-line reference

Commands:

| Command | What it does | Network calls |
| --- | --- | --- |
| `./codex_usage.py` | Opens the menu in an interactive terminal; prints `all` in non-interactive use. | Depends on mode |
| `./codex_usage.py menu` | Opens the interactive menu explicitly. | Yes, for the quick summary and online reports |
| `./codex_usage.py all` | Shows reset credits, local usage, and online usage/profile. | Yes |
| `./codex_usage.py resets` | Shows reset-credit count and expiry. | Yes |
| `./codex_usage.py local-usage` | Shows local Codex metadata and counters only. | No |
| `./codex_usage.py online-usage` | Shows read-only online usage/profile data. | Yes |
| `./codex_usage.py export` | Writes a report beside the script. | Depends on `--report` |

Shared display switches:

| Switch | Available on | Meaning | Default |
| --- | --- | --- | --- |
| `-h`, `--help` | All commands | Show help and exit. | n/a |
| `--colour {auto,always,never}` / `--color {auto,always,never}` | All subcommands | Control terminal colour output. | `auto` |
| `--no-colour` / `--no-color` | All subcommands | Disable colour output. Useful for logs and copied output. | off |
| `--json` | `all`, `resets`, `local-usage`, `online-usage` | Print machine-readable JSON instead of prose/tables. | off |
| `--top N` | `all`, `menu`, `local-usage`, `online-usage`, `export` | Limit ranked rows and Technical details field samples. | `10` for most reports, `30` for `online-usage` |
| `--days N` | `all`, `menu`, `local-usage`, `export` | Number of recent daily local-usage rows to show/include. | `30` |
| `--warn-days N` | `all`, `menu`, `resets`, `export` | Warn when reset credits expire within this many days. Use `0` to disable soon-expiry warnings. | `7` |

Export-only switches:

| Switch | Meaning | Default |
| --- | --- | --- |
| `--report {all,resets,local-usage,online-usage}` | Chooses which report to save. | `all` |
| `--format {txt,json,csv}` | Chooses the export format. | `txt` |

## Settings

The menu and commands use three display settings:

- `top`: how many rows to show in ranked tables, such as top sessions or model usage.
- `days`: how many recent calendar days to show in daily local-usage tables.
- `warn_days`: how many days before reset-credit expiry should trigger a warning. Use `0` to disable soon-expiry warnings.

These settings affect display only. They do not change Codex, your account, or `~/.codex`.

## Privacy and authentication

The script uses your existing Codex login file:

```text
~/.codex/auth.json
```

It reads the access token and account ID from that file to call Codex/ChatGPT backend endpoints. It does not print them.

You do **not** need an OpenAI API key.

The script redacts token-like and identity-like fields before displaying or exporting online responses, including:

- access tokens;
- refresh tokens;
- ID tokens;
- authorisation headers;
- cookies;
- session values;
- account IDs;
- email addresses;
- phone numbers;
- passwords and secrets.

Local usage mode reads metadata and counters from `~/.codex`. It avoids prompt text, assistant text, command text, diffs, transcripts, and secret contents.

## Network behaviour

Local usage mode:

```sh
./codex_usage.py local-usage
```

makes no network calls.

Reset and online usage modes call ChatGPT/Codex backend endpoints with read-only `GET` requests. The main endpoints currently used are:

```text
/wham/rate-limit-reset-credits
/wham/usage
/wham/usage/daily-token-usage-breakdown
/wham/usage/credit-usage-events
/wham/profiles/me
```

These endpoints are undocumented. Treat their output as useful operational information, not as a contractual billing statement.

## Exports

Reports are written to the same directory as `codex_usage.py`. If the script is in `~/Desktop`, the reports will be written to `~/Desktop`. If the script is in a cloned repository, reports will be written inside that repository directory.

Report names look like:

```text
codex_all_report_2026-06-20_114005.txt
codex_resets_report_2026-06-20_114005.json
codex_online-usage_report_2026-06-20_114005.csv
```

The script never removes exported reports. If you export often, you manage those files yourself.

Generated report files matching `codex_*_report_*` are ignored by this repository’s `.gitignore` so they are not accidentally included in Git commits.

## Why the Desktop app may not match this script exactly

The Codex Desktop app can show slightly different limit figures from this script. That is normally not a sign that reset credits are wrong. The likely causes are:

- the Desktop app may use additional internal endpoints or frontend-specific calculations that this script does not call;
- the app may group primary, weekly, promotional, model-specific, or additional-rate-limit buckets differently;
- the script reports the fields returned by `/wham/usage`, including `rate_limit` and `additional_rate_limits`, rather than inventing absolute limits that the endpoint does not expose;
- the values are live and can change between opening the app and running the script;
- undocumented endpoints can change shape without notice.

For reset-credit count and expiry, use the reset-credit report. For rate-limit pressure, treat the script as a transparent read-out of the backend fields it can see, not as a clone of the Desktop UI.

## Accuracy

Local token counters are local Codex counters. They are useful for spotting patterns and large sessions, but they may not match server-side accounting.

Online usage data comes from undocumented backend endpoints. It is useful operational data, not official billing documentation and not guaranteed to match the Desktop app's presentation.

## Troubleshooting

Check that the script is syntactically valid:

```sh
python3 -m py_compile ./codex_usage.py
```

If `./codex_usage.py` says permission is denied, make it executable:

```sh
chmod +x codex_usage.py
```

If the script says `~/.codex/auth.json` is missing or malformed, sign in to Codex first, then run the script again. The script reuses that existing login; it does not ask for, store, or need an OpenAI API key.

If online sections fail but `local-usage` works, the likely causes are network access, an expired Codex login, or undocumented backend endpoints changing. You can still run the local-only report without network access:

```sh
./codex_usage.py local-usage
```

For copy/paste-friendly output, disable colour:

```sh
./codex_usage.py all --no-colour
```

For automation, use JSON output on non-export report commands:

```sh
./codex_usage.py all --json
```

If a numeric option is invalid, the script exits before making requests. `--top` and `--days` must be at least `1`; `--warn-days` must be `0` or greater.

## Licence

This project uses the MIT Licence. See [LICENCE](LICENCE).
