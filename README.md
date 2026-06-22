# Codex Usage

Codex Usage is a local command-line tool for people who want a clear view of their Codex reset credits, rate-limit windows, local usage metadata and read-only online usage/profile data.

The project is intentionally small: one Python file, no package install, no third-party Python dependencies and no OpenAI API key. Run it from the folder that contains `codex_usage.py`, choose the menu or a direct command, and read the report in your terminal.

Use it to see how many reset credits are available, when they expire in your local timezone, whether visible rate-limit windows are close to their limit, and what local Codex metadata says about sessions, models, days and token totals. You can export the same reports as TXT, JSON or CSV files beside the script.

This is not an official OpenAI or Codex tool. It does not redeem credits, buy credits, change your Codex or ChatGPT account, change Codex settings, upload local transcripts, or use OpenAI API billing. The online data comes from undocumented ChatGPT/Codex backend endpoints, so treat it as useful operational information rather than a contractual billing statement.

## Requirements

- Python 3.10 or newer.
- macOS or Linux.
- Local Codex state under `~/.codex` for `local-usage`.
- A Codex login at `~/.codex/auth.json` and network access for `resets`, `online-usage`, `all` and menu quick summaries.

No third-party Python packages are required. Windows is not supported because the script expects Unix-style paths, an executable shebang workflow and a Codex home at `~/.codex`.

The source layout is deliberately small:

```text
.gitattributes
codex_usage.py
img/
LICENCE
README.md
```

## Install And Run

Download or clone this repository, then open a terminal in the folder that contains `codex_usage.py`.

Make the script executable and start it:

```sh
chmod +x codex_usage.py
./codex_usage.py
```

If you prefer not to mark the file executable, run it through Python:

```sh
python3 codex_usage.py
```

You can check the script syntax before running it:

```sh
python3 -m py_compile ./codex_usage.py
```

The syntax check only verifies that Python can parse the script. It does not contact Codex and does not read your account data.

## Use The Reports

In an interactive terminal, running the script without arguments opens the menu. In non-interactive use, the same entry point prints the `all` report.

```sh
./codex_usage.py
```

The menu starts with a quick summary, then offers the report choices and settings:

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

Reports are written for normal reading first. Each major section starts with a short explanation, then shows the main values in labelled tables. Endpoint paths, response shapes and filtered raw fields are collected under `Technical details` near the bottom, so they are available when you need to verify where a value came from without dominating the main report.

You can also call each report directly. Every command supports `-h` and `--help`, and subcommands have their own help:

```sh
./codex_usage.py --help
./codex_usage.py local-usage --help
./codex_usage.py export --help
```

Show everything:

```sh
./codex_usage.py all
```

Show reset credits:

```sh
./codex_usage.py resets
./codex_usage.py resets --warn-days 14
```

Show local usage without network calls:

```sh
./codex_usage.py local-usage
./codex_usage.py local-usage --top 20 --days 60
```

Show read-only online usage/profile data:

```sh
./codex_usage.py online-usage
./codex_usage.py online-usage --top 3
```

For copy/paste-friendly output, scripted checks or logs, disable terminal colour:

```sh
./codex_usage.py local-usage --top 1 --days 1 --no-colour
./codex_usage.py online-usage --top 3 --no-colour
./codex_usage.py resets --no-colour
```

For automation, print machine-readable JSON instead of prose and tables:

```sh
./codex_usage.py all --json
./codex_usage.py resets --json
./codex_usage.py local-usage --json
./codex_usage.py online-usage --json
```

## Screenshots

<!-- markdownlint-disable MD033 -- HTML is used here so GitHub can render bounded thumbnails that link to the full-size screenshots. -->
<p>
  <a href="https://github.com/MacSteini/Codex-Usage/blob/main/img/1.png"><img src="https://github.com/MacSteini/Codex-Usage/raw/main/img/1.png" alt="Codex Usage screenshot 1" width="220"></a>
  <a href="https://github.com/MacSteini/Codex-Usage/blob/main/img/2.png"><img src="https://github.com/MacSteini/Codex-Usage/raw/main/img/2.png" alt="Codex Usage screenshot 2" width="220"></a>
  <a href="https://github.com/MacSteini/Codex-Usage/blob/main/img/3.png"><img src="https://github.com/MacSteini/Codex-Usage/raw/main/img/3.png" alt="Codex Usage screenshot 3" width="220"></a>
  <a href="https://github.com/MacSteini/Codex-Usage/blob/main/img/4.png"><img src="https://github.com/MacSteini/Codex-Usage/raw/main/img/4.png" alt="Codex Usage screenshot 4" width="220"></a>
  <a href="https://github.com/MacSteini/Codex-Usage/blob/main/img/5.png"><img src="https://github.com/MacSteini/Codex-Usage/raw/main/img/5.png" alt="Codex Usage screenshot 5" width="220"></a>
  <a href="https://github.com/MacSteini/Codex-Usage/blob/main/img/6.png"><img src="https://github.com/MacSteini/Codex-Usage/raw/main/img/6.png" alt="Codex Usage screenshot 6" width="220"></a>
</p>
<!-- markdownlint-enable MD033 -->

## Command Reference

| Command | What it does | Network calls |
| --- | --- | --- |
| `./codex_usage.py` | Opens the menu in an interactive terminal; prints `all` in non-interactive use. | Depends on mode |
| `./codex_usage.py menu` | Opens the interactive menu explicitly. | Yes, for the quick summary and online reports |
| `./codex_usage.py all` | Shows reset credits, local usage and online usage/profile. | Yes |
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
| `--top N` | `all`, `menu`, `local-usage`, `online-usage`, `export` | Limit ranked rows and Technical details field samples. | `10` for `all`, `menu`, `local-usage` and `export`; `30` for direct `online-usage` |
| `--days N` | `all`, `menu`, `local-usage`, `export` | Number of recent daily local-usage rows to show/include. | `30` |
| `--warn-days N` | `all`, `menu`, `resets`, `export` | Warn when reset credits expire within this many days. Use `0` to disable soon-expiry warnings. | `7` |

The menu and commands use the same display settings. `top` controls ranked-table length, such as top sessions or model usage. `days` controls how many recent calendar days appear in daily local-usage tables. `warn_days` controls how soon reset-credit expiry should produce a warning; use `0` to disable soon-expiry warnings. These settings affect display and export size only. They do not change Codex, your account or `~/.codex`.

## Exports

Use `export` when you want to save a report beside the script:

```sh
./codex_usage.py export --report all --format txt
./codex_usage.py export --report all --format json
./codex_usage.py export --report all --format csv
```

You can export a single report type:

```sh
./codex_usage.py export --report resets --format txt
./codex_usage.py export --report local-usage --format csv
./codex_usage.py export --report online-usage --format json
```

Export-only switches:

| Switch | Meaning | Default |
| --- | --- | --- |
| `--report {all,resets,local-usage,online-usage}` | Chooses which report to save. | `all` |
| `--format {txt,json,csv}` | Chooses the export format. | `txt` |

Reports are written to the same directory as `codex_usage.py`. If the script is on your Desktop, reports are written to your Desktop. If the script is in a cloned repository, reports are written inside that repository directory.

Report names look like this:

```text
codex_all_report_2026-06-20_114005.txt
codex_resets_report_2026-06-20_114005.json
codex_online-usage_report_2026-06-20_114005.csv
```

The script never removes exported reports. If you export inside a Git checkout, check `git status` before committing and keep generated `codex_*_report_*` files out of the source release.

## Privacy And Authentication

Codex Usage reuses your existing Codex login file:

```text
~/.codex/auth.json
```

The script reads the access token and account ID from that file when it calls Codex/ChatGPT backend endpoints. It does not print them, and you do not need an OpenAI API key.

Online responses are redacted before display or export. Token-like and identity-like fields are filtered by sensitive field name, including access tokens, refresh tokens, ID tokens, authorisation headers, cookies, session values, account IDs, email fields, phone fields, passwords and secrets. Email addresses inside string values are also redacted.

Local usage mode reads metadata and counters from `~/.codex`. It avoids prompt text, assistant text, command text, diffs, transcripts and secret contents.

## Network Behaviour

Local usage mode makes no network calls:

```sh
./codex_usage.py local-usage
```

Reset and online usage modes call undocumented ChatGPT/Codex backend endpoints with read-only `GET` requests. The script uses them for reset credits, rate-limit and usage summaries, daily token breakdowns, credit events and profile metadata. These endpoints may change without notice. Treat their output as operational information that helps you understand the current account state visible to those endpoints, not as an official billing source.

## Accuracy

The Codex Desktop app can show slightly different limit figures from this script. That is normally not a sign that reset credits are wrong. The app may use additional internal endpoints or frontend-specific calculations, group primary, weekly, promotional, model-specific or additional-rate-limit buckets differently, or refresh values at a different time.

For reset-credit count and expiry, use the reset-credit report. For rate-limit pressure, treat Codex Usage as a transparent read-out of the backend fields it can see, including `rate_limit` and `additional_rate_limits`, rather than a clone of the Desktop UI.

Local token counters are local Codex counters. They are useful for spotting patterns and large sessions, but they may not match server-side accounting. Online usage data is useful operational data, not official billing documentation and not guaranteed to match the Desktop app's presentation.

## Troubleshooting

If the script fails before running, first check that Python can parse it:

```sh
python3 -m py_compile ./codex_usage.py
```

If `./codex_usage.py` says permission is denied, make it executable:

```sh
chmod +x codex_usage.py
```

If the script says `~/.codex/auth.json` is missing or malformed, sign in to Codex first, then run the script again. Codex Usage reuses that existing login; it does not ask for, store or need an OpenAI API key.

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

## Contributing

Bug reports, focused fixes and documentation improvements are welcome.

Keep changes narrow and include the checks that match the touched area. For README-only changes, run the repository validation. For script changes, also run the relevant `--help` command, syntax check and Python lint checks:

```sh
python3 -m py_compile ./codex_usage.py
ruff check ./codex_usage.py
ruff format --check ./codex_usage.py
pyflakes ./codex_usage.py
python3 codex_usage.py --help
```

Do not include access tokens, `~/.codex/auth.json`, exported reports, raw backend responses, local transcripts, private prompts, private paths or account data in issues, commits, fixtures or screenshots.

Please report security or privacy issues privately instead of publishing exploit details.

## Licence

This project uses the MIT Licence. See [LICENCE](LICENCE).
