#!/usr/bin/env python3
"""
Codex Usage
===========

Repository: https://github.com/MacSteini/Codex-Usage
Author: MacSteini
Licence: MIT

A single-file command-line tool for Codex users. It shows reset credits,
rate-limit windows, local usage metadata, read-only online usage/profile data,
and report exports beside the script.

It uses the existing Codex login at ~/.codex/auth.json. It does not require an
OpenAI API key. It does not print auth tokens, account IDs, email addresses,
prompts, assistant replies, commands, diffs, transcripts, or secrets.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import textwrap
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

AUTH_PATH = Path("~/.codex/auth.json").expanduser()
CODEX_HOME = Path("~/.codex").expanduser()
SCRIPT_DIR = Path(__file__).resolve().parent
EXPORT_DIR = SCRIPT_DIR
API_BASE = "https://chatgpt.com/backend-api"
ORIGINATOR = "Codex Desktop"
USER_AGENT = "codex-usage-local-script/3.0"
USAGE_FIELDS = [
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
]
ONLINE_ENDPOINTS = {
    "rate_limit_status": "/wham/usage",
    "daily_token_usage_breakdown": "/wham/usage/daily-token-usage-breakdown",
    "credit_usage_events": "/wham/usage/credit-usage-events",
    "profile": "/wham/profiles/me",
}
SENSITIVE_KEY_RE = re.compile(
    r"(access[_-]?token|refresh[_-]?token|id[_-]?token|authorization|secret|password|cookie|session|account[_-]?id|email|phone)",
    re.I,
)
INTERESTING_ONLINE_KEY_RE = re.compile(
    r"(usage|token|credit|limit|remaining|reset|plan|tier|quota|rate|bucket|daily|lifetime|status|used|expires|renew|model|source)",
    re.I,
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ANSI = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}
COLOR_ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None




def die(message: str, exit_code: int = 1) -> None:
    print(f"❌ {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def set_colour_mode(mode: str | None) -> None:
    global COLOR_ENABLED
    if mode == "always":
        COLOR_ENABLED = True
    elif mode == "never":
        COLOR_ENABLED = False
    else:
        COLOR_ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def colour(text: str, name: str) -> str:
    if not COLOR_ENABLED:
        return text
    return f"{ANSI.get(name, '')}{text}{ANSI['reset']}"


def local_now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z %z")


def fmt_int(value: int | float | None) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}"


def fmt_number(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return fmt_int(value)
    if isinstance(value, float):
        if value.is_integer():
            return fmt_int(value)
        return f"{value:,.{decimals}f}"
    return scalar_preview(value) if 'scalar_preview' in globals() else str(value)


def fmt_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}%"


def print_kv(label: str, value: Any, width: int = 28) -> None:
    print(f"{label + ':':<{width}} {value}")


def fmt_local_timestamp(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        try:
            return datetime.fromtimestamp(number).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z %z")
        except (OSError, OverflowError, ValueError):
            return str(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z %z")
        except ValueError:
            return value
    return str(value)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_dt(value: str | None) -> tuple[str, str, str, float | None]:
    dt = parse_dt(value)
    if dt is None:
        return (value or "—", "—", "—", None)

    utc_dt = dt.astimezone(timezone.utc)
    local_dt = dt.astimezone()
    now = datetime.now(timezone.utc)
    delta = utc_dt - now
    days_remaining = delta.total_seconds() / 86400

    if delta.total_seconds() < 0:
        remaining = "expired"
    else:
        remaining = "in " + fmt_duration_seconds(delta.total_seconds())

    utc_text = utc_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    local_text = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z %z")
    return local_text, utc_text, remaining, days_remaining


def fmt_duration_seconds(value: Any) -> str:
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return "—"
    if seconds < 0:
        return "expired"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hr{'s' if hours != 1 else ''}")
    if minutes and len(parts) < 2:
        parts.append(f"{minutes} min{'s' if minutes != 1 else ''}")
    if not parts:
        parts.append(f"{seconds} sec{'s' if seconds != 1 else ''}")
    return ", ".join(parts[:2])


def fmt_epoch_local(value: Any) -> str:
    return fmt_local_timestamp(value)


def display_width(value: str) -> int:
    width = 0
    for char in strip_ansi(value):
        category = unicodedata.category(char)
        if category in {"Mn", "Me", "Cf"}:
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", value)


def pad_display(value: str, width: int) -> str:
    return value + " " * max(0, width - display_width(value))


def truncate_display(value: str, width: int) -> str:
    if display_width(value) <= width:
        return value
    if width <= 1:
        return "…"[:width]
    out = ""
    used = 0
    for char in value:
        if unicodedata.category(char) in {"Mn", "Me", "Cf"}:
            out += char
            continue
        char_width = 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
        if used + char_width > width - 1:
            break
        out += char
        used += char_width
    return out + "…"


def terminal_width() -> int:
    return shutil.get_terminal_size((140, 24)).columns


def make_table(headers: list[str], rows: list[list[str]], max_width: int | None = None) -> str:
    max_width = max_width or min(max(80, terminal_width()), 180)
    clean_rows = [[str(cell) for cell in row] for row in rows]
    widths = [display_width(h) for h in headers]
    for row in clean_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))

    min_widths = [min(max(display_width(headers[i]), 8), widths[i]) for i in range(len(widths))]

    def total_table_width() -> int:
        return sum(widths) + (3 * len(widths)) + 1

    while widths and total_table_width() > max_width:
        candidates = [i for i, w in enumerate(widths) if w > min_widths[i]]
        if not candidates:
            break
        i = max(candidates, key=lambda idx: widths[idx])
        widths[i] -= 1

    def line(left: str, sep: str, right: str, fill: str = "─") -> str:
        return left + sep.join(fill * (w + 2) for w in widths) + right

    def row(cells: list[str]) -> str:
        truncated = [truncate_display(cells[i], widths[i]) for i in range(len(widths))]
        return "│ " + " │ ".join(pad_display(truncated[i], widths[i]) for i in range(len(widths))) + " │"

    out = [line("┌", "┬", "┐"), row(headers), line("├", "┼", "┤")]
    out.extend(row(r) for r in clean_rows)
    out.append(line("└", "┴", "┘"))
    return "\n".join(out)


def print_counter_table(title: str, headers: list[str], rows: list[list[str]]) -> None:
    print(colour(title, "bold"))
    print("-" * len(title))
    if rows:
        print(make_table(headers, rows))
    else:
        print("No data found.")
    print()


def short_path(path_value: str | None, max_chars: int = 48) -> str:
    if not path_value:
        return "—"
    home = str(Path.home())
    text = str(path_value).replace(home, "~")
    if len(text) <= max_chars:
        return text
    parts = Path(text).parts
    if len(parts) >= 3:
        text = f"{parts[0]}/…/{parts[-1]}"
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def section(title: str) -> None:
    print(colour(title, "bold"))
    print("=" * display_width(title))


def explain(text: str) -> None:
    width = min(max(72, terminal_width() - 4), 110)
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if paragraph:
            print(textwrap.fill(paragraph, width=width))
        else:
            print()
    print()



def load_auth() -> tuple[str, str]:
    if not AUTH_PATH.exists():
        die(f"Codex auth file not found: {AUTH_PATH}")

    try:
        auth = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"Could not parse {AUTH_PATH} as JSON: {exc}")
    except OSError as exc:
        die(f"Could not read {AUTH_PATH}: {exc}")

    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        die(f"Unexpected format in {AUTH_PATH}: field 'tokens' is missing.")

    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not access_token or not account_id:
        die(
            "Unexpected format in auth.json: 'tokens.access_token' or "
            "'tokens.account_id' is missing. Are you signed in to Codex CLI/Desktop?"
        )

    return access_token, account_id


def build_url(path_or_url: str) -> str:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    return API_BASE.rstrip("/") + "/" + path_or_url.lstrip("/")


def fetch_json(path_or_url: str, access_token: str, account_id: str, timeout: int = 25) -> dict[str, Any]:
    req = urllib.request.Request(
        build_url(path_or_url),
        headers={
            "Authorization": f"Bearer {access_token}",
            "ChatGPT-Account-ID": account_id,
            "originator": ORIGINATOR,
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:1000]
        return {"ok": False, "status": exc.code, "reason": exc.reason, "body_excerpt": redact(body)}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"Network error: {exc}"}
    except TimeoutError:
        return {"ok": False, "error": "Timed out whilst fetching data."}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"ok": False, "status": status, "error": f"Response was not valid JSON: {exc}", "body_excerpt": redact(raw[:1000])}
    return {"ok": True, "status": status, "data": data}


def redact(value: Any, key: str | None = None) -> Any:
    if key and SENSITIVE_KEY_RE.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, str):
        text = EMAIL_RE.sub("[REDACTED_EMAIL]", value)
        if len(text) > 300:
            return text[:297] + "…"
        return text
    return value




def collect_resets() -> dict[str, Any]:
    access_token, account_id = load_auth()
    response = fetch_json("/wham/rate-limit-reset-credits", access_token, account_id)
    if not response.get("ok"):
        return {"retrieved_at_local": local_now_text(), "ok": False, "error": response}
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    credits_raw = data.get("credits", []) if isinstance(data, dict) else []
    credits = credits_raw if isinstance(credits_raw, list) else []
    normalised = [normalise_credit_for_json(c) for c in credits if isinstance(c, dict)]
    return {
        "retrieved_at_local": local_now_text(),
        "ok": True,
        "available_count": data.get("available_count"),
        "credits_returned": len(normalised),
        "total_earned_count": data.get("total_earned_count"),
        "credits": normalised,
        "note": "Endpoint is undocumented and may change. Token is not printed.",
    }


def normalise_credit_for_json(credit: dict[str, Any]) -> dict[str, Any]:
    local_expiry, utc_expiry, remaining, days_remaining = fmt_dt(credit.get("expires_at"))
    local_granted, utc_granted, _, _ = fmt_dt(credit.get("granted_at"))
    return {
        "reset_type": credit.get("reset_type"),
        "status": credit.get("status"),
        "granted_at": credit.get("granted_at"),
        "granted_at_local": local_granted,
        "granted_at_utc": utc_granted,
        "expires_at": credit.get("expires_at"),
        "expires_at_local": local_expiry,
        "expires_at_utc": utc_expiry,
        "time_remaining": remaining,
        "days_remaining": days_remaining,
        "redeem_started_at": credit.get("redeem_started_at"),
        "redeemed_at": credit.get("redeemed_at"),
    }


def reset_warnings(reset_data: dict[str, Any], warn_days: int) -> list[str]:
    warnings: list[str] = []
    if not reset_data.get("ok", True):
        warnings.append("Could not fetch reset credits.")
        return warnings
    for i, credit in enumerate(reset_data.get("credits", []), start=1):
        status = str(credit.get("status") or "unknown")
        days = credit.get("days_remaining")
        if status == "available" and isinstance(days, (int, float)):
            if days < 0:
                warnings.append(f"Reset #{i} has expired.")
            elif days <= warn_days:
                warnings.append(f"Reset #{i} expires soon: {credit.get('time_remaining')} ({credit.get('expires_at_local')}).")
    return warnings


def print_resets(reset_data: dict[str, Any], warn_days: int = 7) -> None:
    section("Codex Rate-Limit Reset Credits")
    explain("Reset credits are spare one-use allowances for Codex rate limits. This report shows how many are available and when each one expires in your local timezone.")
    if not reset_data.get("ok", True):
        print_counter_table("Reset credit overview", ["Metric", "Value"], [["Retrieved", reset_data.get("retrieved_at_local", local_now_text())], ["Status", colour("error", "red")]])
        print(json.dumps(reset_data.get("error"), indent=2, ensure_ascii=False))
        return
    overview_rows = [
        ["Retrieved", reset_data.get("retrieved_at_local", local_now_text())],
        ["Available resets", reset_data.get("available_count", "—")],
        ["Credits returned", reset_data.get("credits_returned", "—")],
        ["Total earned count", reset_data.get("total_earned_count", "—")],
        ["Expiry warning window", f"{warn_days} day{'s' if warn_days != 1 else ''}"],
    ]
    print_counter_table("Reset credit overview", ["Metric", "Value"], overview_rows)

    warnings = reset_warnings(reset_data, warn_days)
    if warnings:
        print(colour("Warnings", "yellow"))
        for item in warnings:
            print(f"  ⚠️  {item}")
        print()

    credits = reset_data.get("credits", [])
    if not credits:
        print("No reset credits were found in the server response.")
        return

    rows: list[list[str]] = []
    for index, credit in enumerate(credits, start=1):
        status = str(credit.get("status", "unknown"))
        status_text = status
        if status == "available":
            status_text = colour(status_text, "green")
        rows.append([
            str(index),
            status_text,
            str(credit.get("expires_at_local") or "—"),
            str(credit.get("time_remaining") or "—"),
            str(credit.get("granted_at_local") or "—"),
        ])
    print_counter_table("Reset credits", ["#", "Status", "Expires locally", "Time remaining", "Granted locally"], rows)
    print(colour("Technical details", "bold"))
    print("-" * 17)
    explain("These details explain where the values came from. They are shown for transparency and are not needed for normal reading of the report.")
    print_counter_table("Reset endpoint details", ["Metric", "Value"], [
        ["Endpoint", "/backend-api/wham/rate-limit-reset-credits"],
        ["Method", "GET"],
        ["Auth file", f"{AUTH_PATH} (token is not printed)"],
        ["Endpoint status", "undocumented; may change"],
    ])


def cmd_resets(args: argparse.Namespace) -> None:
    set_colour_mode(getattr(args, "colour", None))
    data = collect_resets()
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print_resets(data, warn_days=args.warn_days)




def connect_sqlite_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def sqlite_threads_summary(codex_home: Path, top_n: int) -> dict[str, Any]:
    candidates = [codex_home / "state_5.sqlite", codex_home / "sqlite" / "state_5.sqlite"]
    summaries: list[dict[str, Any]] = []
    for db_path in candidates:
        if not db_path.exists():
            continue
        try:
            con = connect_sqlite_readonly(db_path)
            cur = con.cursor()
            tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "threads" not in tables:
                con.close()
                continue
            cols = [row[1] for row in cur.execute("PRAGMA table_info(threads)")]
            has_tokens = "tokens_used" in cols
            has_model = "model" in cols
            has_created = "created_at" in cols
            has_updated = "updated_at" in cols
            basic: dict[str, Any] = {
                "database": str(db_path),
                "rows": 0,
                "tokens_used_sum": 0,
                "tokens_used_max": 0,
                "created_at_min": None,
                "updated_at_max": None,
                "by_model": [],
            }
            if has_tokens:
                row = cur.execute("SELECT COUNT(*), SUM(COALESCE(tokens_used, 0)), MAX(COALESCE(tokens_used, 0)) FROM threads").fetchone()
                basic["rows"] = int(row[0] or 0)
                basic["tokens_used_sum"] = int(row[1] or 0)
                basic["tokens_used_max"] = int(row[2] or 0)
            else:
                basic["rows"] = int(cur.execute("SELECT COUNT(*) FROM threads").fetchone()[0] or 0)
            if has_created:
                basic["created_at_min"] = cur.execute("SELECT MIN(created_at) FROM threads").fetchone()[0]
            if has_updated:
                basic["updated_at_max"] = cur.execute("SELECT MAX(updated_at) FROM threads").fetchone()[0]
            if has_model and has_tokens:
                for model, rows, tokens in cur.execute(
                    """
                    SELECT COALESCE(NULLIF(model, ''), '(blank)') AS model_name,
                           COUNT(*) AS rows,
                           SUM(COALESCE(tokens_used, 0)) AS tokens
                    FROM threads
                    GROUP BY COALESCE(NULLIF(model, ''), '(blank)')
                    ORDER BY tokens DESC
                    LIMIT ?
                    """,
                    (top_n,),
                ):
                    basic["by_model"].append({"model": model, "threads": int(rows or 0), "tokens_used": int(tokens or 0)})
            con.close()
            summaries.append(basic)
        except sqlite3.Error as exc:
            summaries.append({"database": str(db_path), "error": f"{type(exc).__name__}: {exc}"})
    selected = next((s for s in summaries if s.get("database", "").endswith("state_5.sqlite") and "/sqlite/" not in s.get("database", "")), None)
    if selected is None and summaries:
        selected = summaries[0]
    return {"selected": selected, "all": summaries}


def session_date_from_path(path: Path) -> str | None:
    parts = path.parts
    try:
        idx = parts.index("sessions")
        year, month, day = parts[idx + 1], parts[idx + 2], parts[idx + 3]
        if len(year) == 4 and len(month) == 2 and len(day) == 2:
            return f"{year}-{month}-{day}"
    except (ValueError, IndexError):
        return None
    return None


def scan_sessions_metadata(codex_home: Path, top_n: int = 10) -> dict[str, Any]:
    session_dir = codex_home / "sessions"
    files = sorted(session_dir.rglob("*.jsonl")) if session_dir.exists() else []
    daily_sessions: Counter[str] = Counter()
    daily_usage: dict[str, Counter[str]] = defaultdict(Counter)
    model_sessions: Counter[str] = Counter()
    model_usage: dict[str, Counter[str]] = defaultdict(Counter)
    provider_sessions: Counter[str] = Counter()
    context_windows: Counter[str] = Counter()
    final_totals: list[dict[str, Any]] = []
    final_sum: Counter[str] = Counter()
    parse_errors = 0
    lines_seen = 0
    files_with_usage = 0
    mtime_values: list[datetime] = []

    for file_path in files:
        date_key = session_date_from_path(file_path) or "unknown"
        daily_sessions[date_key] += 1
        try:
            mtime_values.append(datetime.fromtimestamp(file_path.stat().st_mtime).astimezone())
        except OSError:
            pass

        final_usage: dict[str, int] | None = None
        model: str | None = None
        provider: str | None = None
        context_window: int | None = None
        project: str | None = None

        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    lines_seen += 1
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        parse_errors += 1
                        continue
                    if not isinstance(obj, dict):
                        continue
                    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else obj
                    if not isinstance(payload, dict):
                        continue

                    if isinstance(payload.get("model"), str):
                        model = payload["model"]
                    if isinstance(payload.get("model_provider"), str):
                        provider = payload["model_provider"]
                    if isinstance(payload.get("cwd"), str):
                        project = payload["cwd"]

                    info = payload.get("info")
                    if isinstance(info, dict):
                        total_usage = info.get("total_token_usage")
                        if isinstance(total_usage, dict):
                            final_usage = {key: int(total_usage.get(key) or 0) for key in USAGE_FIELDS if isinstance(total_usage.get(key), (int, float))}
                        if isinstance(info.get("model_context_window"), int):
                            context_window = int(info["model_context_window"])
        except OSError:
            parse_errors += 1
            continue

        if model:
            model_sessions[model] += 1
        if provider:
            provider_sessions[provider] += 1
        if context_window is not None:
            context_windows[str(context_window)] += 1
        if final_usage:
            files_with_usage += 1
            for key, value in final_usage.items():
                final_sum[key] += value
                daily_usage[date_key][key] += value
                if model:
                    model_usage[model][key] += value
            final_totals.append({
                "session_file": str(file_path.relative_to(codex_home)),
                "date": date_key,
                "model": model or "—",
                "project": short_path(project),
                "usage": final_usage,
            })

    final_totals.sort(key=lambda item: item["usage"].get("total_tokens", 0), reverse=True)
    daily_usage_rows = []
    for day in sorted(daily_sessions):
        row = {"date": day, "sessions": daily_sessions[day]}
        row.update({field: int(daily_usage[day].get(field, 0)) for field in USAGE_FIELDS})
        daily_usage_rows.append(row)

    return {
        "session_files": len(files),
        "jsonl_lines_scanned": lines_seen,
        "parse_or_read_errors": parse_errors,
        "files_with_final_token_totals": files_with_usage,
        "file_mtime_start_local": min(mtime_values).strftime("%Y-%m-%d %H:%M:%S %Z %z") if mtime_values else None,
        "file_mtime_end_local": max(mtime_values).strftime("%Y-%m-%d %H:%M:%S %Z %z") if mtime_values else None,
        "final_token_totals_sum": dict(final_sum),
        "models_by_session": model_sessions.most_common(top_n),
        "model_token_totals": {model: dict(counter) for model, counter in model_usage.items()},
        "providers_by_session": provider_sessions.most_common(20),
        "context_windows_by_session": context_windows.most_common(20),
        "daily_usage": daily_usage_rows,
        "top_sessions_by_total_tokens": final_totals[:top_n],
    }


def collect_local_usage(codex_home: Path, top_n: int) -> dict[str, Any]:
    if not codex_home.exists():
        die(f"Codex home not found: {codex_home}")
    return {
        "retrieved_at_local": local_now_text(),
        "codex_home": str(codex_home),
        "network_calls_made": 0,
        "privacy_note": "Local metadata only; prompt/assistant/transcript contents are not printed.",
        "sqlite_threads": sqlite_threads_summary(codex_home, top_n=top_n),
        "sessions": scan_sessions_metadata(codex_home, top_n=top_n),
    }


def local_hints(local_data: dict[str, Any], high_session_threshold: int = 500_000_000) -> list[str]:
    hints: list[str] = []
    sessions = local_data.get("sessions", {})
    totals = sessions.get("final_token_totals_sum", {}) if isinstance(sessions, dict) else {}
    total_tokens = int(totals.get("total_tokens") or 0)
    input_tokens = int(totals.get("input_tokens") or 0)
    cached = int(totals.get("cached_input_tokens") or 0)
    if input_tokens:
        cached_ratio = cached / input_tokens * 100
        if cached_ratio >= 80:
            hints.append(f"Cached input is high: {cached_ratio:.1f}% of input tokens were cached locally.")
    top_sessions = sessions.get("top_sessions_by_total_tokens", []) if isinstance(sessions, dict) else []
    high_sessions = [s for s in top_sessions if s.get("usage", {}).get("total_tokens", 0) >= high_session_threshold]
    if high_sessions:
        hints.append(f"{len(high_sessions)} top session(s) are above {fmt_int(high_session_threshold)} total tokens.")
    selected = local_data.get("sqlite_threads", {}).get("selected") if isinstance(local_data.get("sqlite_threads"), dict) else None
    if selected and isinstance(selected.get("by_model"), list) and total_tokens:
        top = selected["by_model"][0] if selected["by_model"] else None
        if top:
            share = int(top.get("tokens_used") or 0) / max(1, int(selected.get("tokens_used_sum") or 1)) * 100
            if share >= 90:
                hints.append(f"Model {top.get('model')} dominates local usage at {share:.1f}% of SQLite tokens_used.")
    errors = int(sessions.get("parse_or_read_errors") or 0) if isinstance(sessions, dict) else 0
    if errors:
        hints.append(f"{errors} local session parse/read error(s) were encountered.")
    return hints


def print_local_usage(data: dict[str, Any], top: int, days: int) -> None:
    selected = data["sqlite_threads"].get("selected")
    sessions = data["sessions"]
    section("Codex Local Usage Summary")
    explain("This section reads Codex data already stored on this machine. It is useful for spotting usage patterns and unusually large sessions; it is not a billing statement.")
    print_counter_table("Local report overview", ["Metric", "Value"], [
        ["Retrieved", data["retrieved_at_local"]],
        ["Codex home", data["codex_home"]],
        ["Network calls made", data["network_calls_made"]],
        ["Privacy", "metadata only; no prompts or transcripts printed"],
    ])

    hints = local_hints(data)
    if hints:
        print(colour("Highlights", "cyan"))
        for item in hints:
            print(f"  • {item}")
        print()

    print(colour("SQLite thread counters", "bold"))
    print("-" * 22)
    explain("Codex keeps a small local SQLite database of conversation threads. A thread is roughly a saved Codex conversation. The token counter here is Codex's local running total for those threads.")
    if selected and not selected.get("error"):
        sqlite_rows = [
            ["Database", selected.get("database") or "—"],
            ["Threads", fmt_int(selected.get("rows"))],
            ["Tokens used, total", fmt_int(selected.get("tokens_used_sum"))],
            ["Tokens used, max thread", fmt_int(selected.get("tokens_used_max"))],
            ["Oldest thread timestamp", fmt_local_timestamp(selected.get("created_at_min"))],
            ["Newest thread timestamp", fmt_local_timestamp(selected.get("updated_at_max"))],
        ]
        print_counter_table("SQLite thread counter details", ["Metric", "Value"], sqlite_rows)
    elif selected and selected.get("error"):
        print_counter_table("SQLite thread counter details", ["Metric", "Value"], [["Database", selected.get("database") or "—"], ["Error", selected.get("error")]])
    else:
        print_counter_table("SQLite thread counter details", ["Metric", "Value"], [])

    by_model_rows = []
    if selected and isinstance(selected.get("by_model"), list):
        total_sqlite = max(1, int(selected.get("tokens_used_sum") or 0))
        for item in selected["by_model"][:top]:
            tokens = int(item.get("tokens_used") or 0)
            threads = int(item.get("threads") or 0)
            by_model_rows.append([
                str(item.get("model", "—")),
                fmt_int(threads),
                fmt_int(tokens),
                fmt_int(tokens // max(1, threads)),
                fmt_percent(tokens / total_sqlite * 100),
            ])
    explain("This table groups the local thread counters by model so you can see which model accounts for most recorded usage on this machine.")
    print_counter_table("Tokens by model, from SQLite", ["Model", "Threads", "Tokens", "Avg/thread", "Share"], by_model_rows)

    print(colour("Session JSONL metadata", "bold"))
    print("-" * 22)
    explain("Codex also writes session files in JSONL format, one JSON record per line. This script scans metadata and token counters from those files, not prompt or transcript text.")
    session_meta_rows = [
        ["Session files", fmt_int(sessions.get("session_files"))],
        ["Files with token totals", fmt_int(sessions.get("files_with_final_token_totals"))],
        ["JSONL lines scanned", fmt_int(sessions.get("jsonl_lines_scanned"))],
        ["Parse/read errors", fmt_int(sessions.get("parse_or_read_errors"))],
        ["File mtime range", f"{sessions.get('file_mtime_start_local') or '—'} → {sessions.get('file_mtime_end_local') or '—'}"],
    ]
    print_counter_table("Session JSONL metadata details", ["Metric", "Value"], session_meta_rows)

    totals = sessions.get("final_token_totals_sum", {})
    token_rows = [[field.replace("_", " ").title(), fmt_int(totals.get(field))] for field in USAGE_FIELDS]
    explain("These totals use the last token counter seen in each session file. That avoids obvious double-counting, but the result is still an operational estimate rather than official billing data.")
    print_counter_table("Approximate token totals, from final session counters", ["Field", "Total"], token_rows)

    daily = sessions.get("daily_usage", [])
    recent_daily = daily[-days:] if days > 0 else daily
    daily_rows = [[
        str(row.get("date")),
        fmt_int(row.get("sessions")),
        fmt_int(row.get("total_tokens")),
        fmt_int(row.get("output_tokens")),
    ] for row in recent_daily]
    explain("Daily totals show when local Codex activity happened. They are grouped by the session file dates available on this machine.")
    print_counter_table(f"Daily local token totals, last {len(recent_daily)} days", ["Date", "Sessions", "Total tokens", "Output tokens"], daily_rows)

    model_token_totals = sessions.get("model_token_totals", {})
    model_rows = []
    total_session_tokens = max(1, int(totals.get("total_tokens") or 0))
    for model, count in sessions.get("models_by_session", [])[:top]:
        model_total = int(model_token_totals.get(model, {}).get("total_tokens", 0))
        model_rows.append([str(model or "—"), fmt_int(count), fmt_int(model_total), fmt_percent(model_total / total_session_tokens * 100)])
    explain("This table comes from the session files rather than the SQLite thread database. It is a second local view of which models appear in your Codex history.")
    print_counter_table("Models seen in session metadata", ["Model", "Sessions", "Final tokens", "Share"], model_rows)

    top_rows = []
    for item in sessions.get("top_sessions_by_total_tokens", [])[:top]:
        usage = item.get("usage", {})
        top_rows.append([
            str(item.get("date", "—")),
            str(item.get("model", "—")),
            fmt_int(usage.get("total_tokens")),
            fmt_int(usage.get("output_tokens")),
            str(item.get("project", "—")),
            str(item.get("session_file", "—")),
        ])
    explain("Top sessions are the largest local sessions by total token counter. Use this to find projects or conversations that dominate local usage.")
    print_counter_table("Top sessions by total tokens", ["Date", "Model", "Total", "Output", "Project", "Session file"], top_rows)

    print("Notes")
    print("-----")
    print("• This mode is local-only and made no network calls.")
    print("• SQLite 'tokens_used' is Codex's local counter; it may not equal billable server-side usage.")
    print("• Session token totals are taken from the final total_token_usage seen per session file to avoid obvious double-counting.")


def cmd_local_usage(args: argparse.Namespace) -> None:
    set_colour_mode(getattr(args, "colour", None))
    data = collect_local_usage(CODEX_HOME, top_n=args.top)
    if args.json:
        limit_local_usage_days(data, args.days)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print_local_usage(data, top=args.top, days=args.days)




def collect_online_usage() -> dict[str, Any]:
    access_token, account_id = load_auth()
    out: dict[str, Any] = {
        "retrieved_at_local": local_now_text(),
        "network_calls_made": 0,
        "endpoints": {},
        "privacy_note": "Responses are redacted before display/export. Only read-only GET endpoints are used.",
    }
    for name, path in ONLINE_ENDPOINTS.items():
        response = fetch_json(path, access_token, account_id)
        out["network_calls_made"] += 1
        if response.get("ok"):
            out["endpoints"][name] = {"path": path, "ok": True, "status": response.get("status"), "data": redact(response.get("data"))}
        else:
            out["endpoints"][name] = {"path": path, "ok": False, "error": redact(response)}
    return out


def flatten_interesting(obj: Any, prefix: str = "", rows: list[tuple[str, str]] | None = None, limit: int = 80) -> list[tuple[str, str]]:
    rows = rows if rows is not None else []
    if len(rows) >= limit:
        return rows
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (dict, list)):
                flatten_interesting(value, path, rows, limit)
            elif INTERESTING_ONLINE_KEY_RE.search(path):
                rows.append((path, scalar_preview(value)))
                if len(rows) >= limit:
                    break
    elif isinstance(obj, list):
        if prefix and INTERESTING_ONLINE_KEY_RE.search(prefix):
            rows.append((prefix, f"list[{len(obj)}]"))
        for i, value in enumerate(obj[:10]):
            if isinstance(value, (dict, list)):
                flatten_interesting(value, f"{prefix}[{i}]", rows, limit)
    return rows


def scalar_preview(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return f"{type(value).__name__}[{len(value)}]"
    text = str(value)
    return truncate_display(text, 80)


def online_hints(data: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    for name, item in data.get("endpoints", {}).items():
        if not item.get("ok"):
            hints.append(f"{name} failed or is unavailable: {item.get('error')}")
    return hints


def get_nested(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def interpret_limit_window(prefix: str, window: Any) -> list[list[str]]:
    if not isinstance(window, dict):
        return []
    rows: list[list[str]] = []
    used = window.get("used_percent")
    reset_after = window.get("reset_after_seconds")
    reset_at = window.get("reset_at")
    if used is not None:
        rows.append([f"{prefix} used", f"{used}%"])
    if reset_after is not None:
        rows.append([f"{prefix} resets in", fmt_duration_seconds(reset_after)])
    if reset_at is not None:
        rows.append([f"{prefix} resets at", fmt_epoch_local(reset_at)])
    return rows


def interpreted_online_summary(data: dict[str, Any]) -> list[list[str]]:
    endpoints = data.get("endpoints", {}) if isinstance(data, dict) else {}
    usage_item = endpoints.get("rate_limit_status", {}) if isinstance(endpoints, dict) else {}
    usage = usage_item.get("data") if isinstance(usage_item, dict) and usage_item.get("ok") else None
    profile_item = endpoints.get("profile", {}) if isinstance(endpoints, dict) else {}
    profile = profile_item.get("data") if isinstance(profile_item, dict) and profile_item.get("ok") else None
    daily_item = endpoints.get("daily_token_usage_breakdown", {}) if isinstance(endpoints, dict) else {}
    daily = daily_item.get("data") if isinstance(daily_item, dict) and daily_item.get("ok") else None

    rows: list[list[str]] = []
    if isinstance(usage, dict):
        rows.append(["Plan", scalar_preview(usage.get("plan_type") or "—")])
        rate_limit = usage.get("rate_limit")
        if isinstance(rate_limit, dict):
            rows.append(["Primary limit allowed", str(rate_limit.get("allowed", "—"))])
            rows.append(["Primary limit reached", str(rate_limit.get("limit_reached", "—"))])
            rows.extend(interpret_limit_window("Primary window", rate_limit.get("primary_window")))
            rows.extend(interpret_limit_window("Weekly window", rate_limit.get("secondary_window")))
        credits = usage.get("credits")
        if isinstance(credits, dict):
            rows.append(["Credits balance", fmt_int(credits.get("balance")) if isinstance(credits.get("balance"), (int, float)) else scalar_preview(credits.get("balance"))])
            rows.append(["Has credits", str(credits.get("has_credits", "—"))])
            rows.append(["Unlimited credits", str(credits.get("unlimited", "—"))])
        add = usage.get("additional_rate_limits")
        if isinstance(add, list) and add:
            for index, item in enumerate(add, start=1):
                if not isinstance(item, dict):
                    continue
                name = item.get("limit_name") or item.get("metered_feature") or f"Additional limit {index}"
                limit = item.get("rate_limit")
                if isinstance(limit, dict):
                    rows.append([f"{name} reached", str(limit.get("limit_reached", "—"))])
                    rows.extend(interpret_limit_window(f"{name} primary", limit.get("primary_window")))
                    rows.extend(interpret_limit_window(f"{name} weekly", limit.get("secondary_window")))
    if isinstance(profile, dict):
        stats = profile.get("stats") if isinstance(profile.get("stats"), dict) else {}
        rows.append(["Lifetime tokens", fmt_int(stats.get("lifetime_tokens"))])
        rows.append(["Peak daily tokens", fmt_int(stats.get("peak_daily_tokens"))])
        effort = stats.get("most_used_reasoning_effort")
        effort_pct = stats.get("most_used_reasoning_effort_percentage")
        if effort is not None:
            rows.append(["Most used reasoning effort", f"{effort} ({fmt_percent(float(effort_pct)) if isinstance(effort_pct, (int, float)) else '—'})"])
    if isinstance(daily, dict):
        points = daily.get("data")
        if isinstance(points, list) and points:
            latest = points[-1] if isinstance(points[-1], dict) else None
            if latest:
                date = latest.get("date") or latest.get("start_date") or latest.get("bucket_start_date") or "latest bucket"
                total = latest.get("credits") or latest.get("total") or latest.get("total_credits")
                if total is not None:
                    rows.append([f"Daily breakdown {date}", scalar_preview(total)])
    return rows


def print_interpreted_online_summary(data: dict[str, Any]) -> None:
    rows = interpreted_online_summary(data)
    if not rows:
        return
    explain("This is the plain-English view of the online usage response: plan, current rate-limit pressure, reset times, credit status, and lifetime usage where available.")
    print_counter_table("Interpreted online summary", ["Metric", "Value"], rows)


ONLINE_ENDPOINT_LABELS = {
    "rate_limit_status": "Rate limit status",
    "daily_token_usage_breakdown": "Daily online usage breakdown",
    "credit_usage_events": "Credit usage events",
    "profile": "Profile statistics",
}


def endpoint_label(name: str) -> str:
    return ONLINE_ENDPOINT_LABELS.get(name, name.replace("_", " ").title())


def endpoint_explanation(name: str) -> str:
    explanations = {
        "rate_limit_status": "This section shows whether Codex says you are currently allowed to use the service, how much of each visible rate-limit window is used, and when those windows reset.",
        "daily_token_usage_breakdown": "This section summarises the recent online daily usage breakdown returned by Codex. The endpoint reports its own unit, so the table labels use that unit rather than assuming credits or tokens.",
        "credit_usage_events": "This section lists credit-related events when the backend returns any. If the table is empty, the endpoint did not report credit events for this account at the time of the check.",
        "profile": "This section shows account-level usage statistics returned by the profile endpoint, such as lifetime tokens, streaks, and recent daily token buckets.",
    }
    return explanations.get(name, "This section shows the readable usage-related fields returned by this endpoint.")


def endpoint_overview_rows(name: str, item: dict[str, Any], data_obj: Any) -> list[list[str]]:
    rows = [
        ["Endpoint", item.get("path") or "—"],
        ["HTTP status", str(item.get("status", "—"))],
        ["Shape", type(data_obj).__name__],
    ]
    if isinstance(data_obj, dict):
        rows.append(["Top-level keys", ", ".join(list(data_obj.keys())[:12]) or "—"])
        if isinstance(data_obj.get("data"), list):
            rows.append(["Rows returned", fmt_int(len(data_obj.get("data") or []))])
    elif isinstance(data_obj, list):
        rows.append(["Rows returned", fmt_int(len(data_obj))])
    return rows


def bool_text(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return scalar_preview(value)


def window_row(label: str, window: Any) -> list[str]:
    if not isinstance(window, dict):
        return [label, "—", "—", "—"]
    return [
        label,
        f"{window.get('used_percent')}%" if window.get("used_percent") is not None else "—",
        fmt_duration_seconds(window.get("reset_after_seconds")),
        fmt_epoch_local(window.get("reset_at")),
    ]


def print_rate_limit_status_tables(item: dict[str, Any], data_obj: dict[str, Any], top: int) -> None:
    rate_limit = data_obj.get("rate_limit") if isinstance(data_obj.get("rate_limit"), dict) else {}
    credits = data_obj.get("credits") if isinstance(data_obj.get("credits"), dict) else {}
    status_rows = [
        ["Plan", scalar_preview(data_obj.get("plan_type") or "—")],
        ["Allowed right now", bool_text(rate_limit.get("allowed"))],
        ["Limit reached", bool_text(rate_limit.get("limit_reached"))],
        ["Rate-limit reached type", scalar_preview(data_obj.get("rate_limit_reached_type") or "—")],
        ["Credit balance", scalar_preview(credits.get("balance") if credits else "—")],
        ["Has credits", bool_text(credits.get("has_credits") if credits else None)],
        ["Unlimited credits", bool_text(credits.get("unlimited") if credits else None)],
        ["Overage limit reached", bool_text(credits.get("overage_limit_reached") if credits else None)],
    ]
    print_counter_table("Rate limit status details", ["Metric", "Value"], status_rows)

    window_rows = [
        window_row("Primary window", rate_limit.get("primary_window")),
        window_row("Weekly window", rate_limit.get("secondary_window")),
    ]
    print_counter_table("Rate-limit windows", ["Window", "Used", "Resets in", "Resets at"], window_rows)

    additional = data_obj.get("additional_rate_limits")
    add_rows: list[list[str]] = []
    if isinstance(additional, list):
        for index, entry in enumerate(additional[:top], start=1):
            if not isinstance(entry, dict):
                continue
            limit = entry.get("rate_limit") if isinstance(entry.get("rate_limit"), dict) else {}
            primary = limit.get("primary_window") if isinstance(limit.get("primary_window"), dict) else {}
            weekly = limit.get("secondary_window") if isinstance(limit.get("secondary_window"), dict) else {}
            add_rows.append([
                str(entry.get("limit_name") or entry.get("metered_feature") or f"Additional limit {index}"),
                bool_text(limit.get("limit_reached")),
                f"{primary.get('used_percent')}%" if primary.get("used_percent") is not None else "—",
                fmt_duration_seconds(primary.get("reset_after_seconds")),
                f"{weekly.get('used_percent')}%" if weekly.get("used_percent") is not None else "—",
                fmt_duration_seconds(weekly.get("reset_after_seconds")),
            ])
    print_counter_table("Additional rate limits", ["Name", "Reached", "Primary used", "Primary resets in", "Weekly used", "Weekly resets in"], add_rows)


def top_name_value(values: Any) -> tuple[str, Any]:
    if not isinstance(values, dict) or not values:
        return "—", None
    name, value = max(values.items(), key=lambda item: float(item[1] or 0) if isinstance(item[1], (int, float)) else -1)
    return str(name), value


def model_credit_total(models: Any) -> float | None:
    if not isinstance(models, list):
        return None
    total = 0.0
    found = False
    for model in models:
        if isinstance(model, dict) and isinstance(model.get("credits"), (int, float)):
            total += float(model["credits"])
            found = True
    return total if found else None


def print_daily_breakdown_tables(item: dict[str, Any], data_obj: dict[str, Any], top: int) -> None:
    points = data_obj.get("data") if isinstance(data_obj.get("data"), list) else []
    units = scalar_preview(data_obj.get("units") or "usage units")
    group_by = scalar_preview(data_obj.get("group_by") or "date")
    unit_label = units if units != "—" else "value"
    print_counter_table("Daily breakdown metadata", ["Metric", "Value"], [["Units", units], ["Grouped by", group_by], ["Days returned", fmt_int(len(points))]])

    recent = points[-top:] if top > 0 else points
    rows: list[list[str]] = []
    latest_surfaces: dict[str, Any] | None = None
    latest_models: list[Any] | None = None
    for point in recent:
        if not isinstance(point, dict):
            continue
        surfaces = point.get("product_surface_usage_values") if isinstance(point.get("product_surface_usage_values"), dict) else {}
        models = point.get("models") if isinstance(point.get("models"), list) else []
        surface_name, surface_value = top_name_value(surfaces)
        top_model = "—"
        top_model_credits = None
        if models:
            model = max([m for m in models if isinstance(m, dict)], key=lambda m: float(m.get("credits") or 0), default=None)
            if model:
                top_model = str(model.get("model") or "—")
                top_model_credits = model.get("credits")
        total = model_credit_total(models)
        rows.append([
            str(point.get("date") or point.get("start_date") or "—"),
            fmt_number(total),
            f"{surface_name} ({fmt_number(surface_value)})" if surface_value is not None else surface_name,
            f"{top_model} ({fmt_number(top_model_credits)})" if top_model_credits is not None else top_model,
        ])
        latest_surfaces = surfaces
        latest_models = models
    print_counter_table(f"Daily online usage, latest {len(rows)} days", ["Date", f"Total {unit_label}", "Top surface", "Top model"], rows)

    if latest_surfaces:
        surface_rows = [[name, fmt_number(value)] for name, value in sorted(latest_surfaces.items(), key=lambda item: float(item[1] or 0) if isinstance(item[1], (int, float)) else 0, reverse=True)[:top]]
        print_counter_table("Latest day by product surface", ["Surface", unit_label.title()], surface_rows)
    if latest_models:
        model_rows = []
        for model in sorted([m for m in latest_models if isinstance(m, dict)], key=lambda m: float(m.get("credits") or 0), reverse=True)[:top]:
            model_rows.append([str(model.get("model") or "—"), str(model.get("speed") or "—"), fmt_number(model.get("credits"))])
        print_counter_table("Latest day by model", ["Model", "Speed", unit_label.title()], model_rows)


def print_credit_events_tables(item: dict[str, Any], data_obj: dict[str, Any], top: int) -> None:
    events = data_obj.get("data") if isinstance(data_obj.get("data"), list) else []
    rows: list[list[str]] = []
    for event in events[:top]:
        if not isinstance(event, dict):
            continue
        date = event.get("created_at") or event.get("timestamp") or event.get("date") or event.get("start_date") or "—"
        rows.append([
            fmt_local_timestamp(date) if date != "—" else "—",
            scalar_preview(event.get("type") or event.get("event_type") or event.get("reason") or "—"),
            fmt_number(event.get("credits") or event.get("amount") or event.get("delta")),
            scalar_preview(event.get("description") or event.get("title") or event.get("message") or "—"),
        ])
    print_counter_table("Credit usage events", ["Date", "Event", "Credits", "Description"], rows)


def print_profile_tables(item: dict[str, Any], data_obj: dict[str, Any], top: int) -> None:
    stats = data_obj.get("stats") if isinstance(data_obj.get("stats"), dict) else {}
    profile = data_obj.get("profile") if isinstance(data_obj.get("profile"), dict) else {}
    rows = [
        ["Lifetime tokens", fmt_int(stats.get("lifetime_tokens"))],
        ["Peak daily tokens", fmt_int(stats.get("peak_daily_tokens"))],
        ["Current streak", f"{fmt_int(stats.get('current_streak_days'))} days"],
        ["Longest streak", f"{fmt_int(stats.get('longest_streak_days'))} days"],
        ["Total threads", fmt_int(stats.get("total_threads"))],
        ["Fast mode usage", fmt_percent(float(stats.get("fast_mode_usage_percentage"))) if isinstance(stats.get("fast_mode_usage_percentage"), (int, float)) else "—"],
        ["Most used reasoning effort", scalar_preview(stats.get("most_used_reasoning_effort") or "—")],
        ["Reasoning effort share", fmt_percent(float(stats.get("most_used_reasoning_effort_percentage"))) if isinstance(stats.get("most_used_reasoning_effort_percentage"), (int, float)) else "—"],
        ["Profile fields present", ", ".join(list(profile.keys())[:8]) or "—"],
    ]
    print_counter_table("Profile statistics", ["Metric", "Value"], rows)

    daily = stats.get("daily_usage_buckets") if isinstance(stats.get("daily_usage_buckets"), list) else []
    daily_rows = [[str(point.get("start_date") or "—"), fmt_int(point.get("tokens"))] for point in daily[-top:] if isinstance(point, dict)]
    print_counter_table(f"Profile daily tokens, latest {len(daily_rows)} days", ["Date", "Tokens"], daily_rows)


def print_generic_endpoint_table(name: str, item: dict[str, Any], data_obj: Any, top: int) -> None:
    rows = [[path, value] for path, value in flatten_interesting(data_obj, limit=top)]
    print_counter_table(f"{endpoint_label(name)} fields", ["Field", "Value"], rows)


def print_online_endpoint(name: str, item: dict[str, Any], top: int) -> None:
    title = endpoint_label(name)
    print(colour(title, "bold"))
    print("-" * min(display_width(title), 80))
    explain(endpoint_explanation(name))
    if not item.get("ok"):
        print_counter_table("Endpoint status", ["Metric", "Value"], [["Status", "error"], ["Error", json.dumps(item.get("error"), ensure_ascii=False)]])
        return
    data_obj = item.get("data")
    if name == "rate_limit_status" and isinstance(data_obj, dict):
        print_rate_limit_status_tables(item, data_obj, top)
    elif name == "daily_token_usage_breakdown" and isinstance(data_obj, dict):
        print_daily_breakdown_tables(item, data_obj, top)
    elif name == "credit_usage_events" and isinstance(data_obj, dict):
        print_credit_events_tables(item, data_obj, top)
    elif name == "profile" and isinstance(data_obj, dict):
        print_profile_tables(item, data_obj, top)
    else:
        print_generic_endpoint_table(name, item, data_obj, top)


def print_technical_endpoint_details(name: str, item: dict[str, Any], top: int) -> None:
    title = f"{endpoint_label(name)} technical details"
    print(colour(title, "bold"))
    print("-" * min(display_width(title), 80))
    if not item.get("ok"):
        print_counter_table("Endpoint metadata", ["Metric", "Value"], [["Endpoint", item.get("path") or "—"], ["Status", "error"], ["Error", json.dumps(item.get("error"), ensure_ascii=False)]])
        return
    data_obj = item.get("data")
    print_counter_table("Endpoint metadata", ["Metric", "Value"], endpoint_overview_rows(name, item, data_obj))
    rows = [[path, value] for path, value in flatten_interesting(data_obj, limit=top)]
    print_counter_table("Filtered raw fields", ["Field", "Value"], rows)


def print_online_technical_details(data: dict[str, Any], top: int) -> None:
    print(colour("Technical details", "bold"))
    print("-" * 17)
    explain("These details are kept at the bottom for transparency. They show endpoint paths, response shapes, and a small filtered sample of raw usage-like fields; they are not the primary user-facing report.")
    for name, item in data.get("endpoints", {}).items():
        print_technical_endpoint_details(name, item, top)
        print()


def collect_quick_summary() -> dict[str, Any]:
    return {
        "retrieved_at_local": local_now_text(),
        "reset_credits": collect_resets(),
        "online_usage": collect_online_usage(),
    }


def quick_summary_lines(summary: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    resets = summary.get("reset_credits", {}) if isinstance(summary, dict) else {}
    online = summary.get("online_usage", {}) if isinstance(summary, dict) else {}
    if isinstance(resets, dict) and resets.get("ok", True):
        lines.append(f"Available resets: {resets.get('available_count', '—')}")
        credits = resets.get("credits", [])
        available = [c for c in credits if isinstance(c, dict) and c.get("status") == "available"] if isinstance(credits, list) else []
        if available:
            next_expiry = min(available, key=lambda c: c.get("days_remaining") if isinstance(c.get("days_remaining"), (int, float)) else 10**9)
            lines.append(f"Next reset expiry: {next_expiry.get('time_remaining', '—')}")
    endpoints = online.get("endpoints", {}) if isinstance(online, dict) else {}
    usage_item = endpoints.get("rate_limit_status", {}) if isinstance(endpoints, dict) else {}
    usage = usage_item.get("data") if isinstance(usage_item, dict) and usage_item.get("ok") else None
    if isinstance(usage, dict):
        lines.append(f"Plan: {usage.get('plan_type', '—')}")
        primary = get_nested(usage, "rate_limit", "primary_window", "used_percent")
        weekly = get_nested(usage, "rate_limit", "secondary_window", "used_percent")
        primary_reset = get_nested(usage, "rate_limit", "primary_window", "reset_after_seconds")
        if primary is not None:
            lines.append(f"Primary limit used: {primary}%")
        if weekly is not None:
            lines.append(f"Weekly limit used: {weekly}%")
        if primary_reset is not None:
            lines.append(f"Primary resets in: {fmt_duration_seconds(primary_reset)}")
    profile_item = endpoints.get("profile", {}) if isinstance(endpoints, dict) else {}
    profile = profile_item.get("data") if isinstance(profile_item, dict) and profile_item.get("ok") else None
    lifetime = get_nested(profile, "stats", "lifetime_tokens") if isinstance(profile, dict) else None
    if lifetime is not None:
        lines.append(f"Lifetime tokens: {fmt_int(lifetime)}")
    return lines or ["Quick summary unavailable; choose a report for details."]


def print_quick_summary(summary: dict[str, Any], width: int | None = None) -> None:
    menu_box("Quick Summary", quick_summary_lines(summary), width=width)


def print_online_usage(data: dict[str, Any], top: int = 30) -> None:
    section("Codex Online Usage / Profile")
    explain("This section asks Codex's read-only backend endpoints what they currently know about your plan, rate-limit windows, credits, and profile statistics. It uses your existing Codex login, not an API key.")
    print_counter_table("Online report overview", ["Metric", "Value"], [
        ["Retrieved", data.get("retrieved_at_local")],
        ["Network calls made", data.get("network_calls_made")],
        ["Methods", "GET only"],
        ["Privacy", "responses redacted before display/export"],
    ])

    hints = online_hints(data)
    if hints:
        print(colour("Endpoint notes", "yellow"))
        for item in hints:
            print(f"  ⚠️  {item}")
        print()

    print_interpreted_online_summary(data)

    explain("The endpoint sections below use readable labels first. Technical endpoint paths and filtered raw fields are collected later under Technical details.")

    for name, item in data.get("endpoints", {}).items():
        print_online_endpoint(name, item, top)
        print()
    print_online_technical_details(data, top)
    print("Note: These endpoints are undocumented and may change.")


def cmd_online_usage(args: argparse.Namespace) -> None:
    set_colour_mode(getattr(args, "colour", None))
    data = collect_online_usage()
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print_online_usage(data, top=args.top)




def collect_all(top_n: int) -> dict[str, Any]:
    return {
        "retrieved_at_local": local_now_text(),
        "reset_credits": collect_resets(),
        "local_usage": collect_local_usage(CODEX_HOME, top_n=top_n),
        "online_usage": collect_online_usage(),
    }


def print_all(data: dict[str, Any], top: int, days: int, warn_days: int) -> None:
    print_resets(data["reset_credits"], warn_days=warn_days)
    print("\n" + "=" * min(terminal_width(), 100) + "\n")
    print_local_usage(data["local_usage"], top=top, days=days)
    print("\n" + "=" * min(terminal_width(), 100) + "\n")
    print_online_usage(data["online_usage"], top=top)


def cmd_all(args: argparse.Namespace) -> None:
    set_colour_mode(getattr(args, "colour", None))
    data = collect_all(args.top)
    if args.json:
        limit_local_usage_days(data.get("local_usage"), args.days)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print_all(data, top=args.top, days=args.days, warn_days=args.warn_days)


def render_text(func: Callable[[argparse.Namespace], None], args: argparse.Namespace) -> str:
    previous = COLOR_ENABLED
    try:
        set_colour_mode("never")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            func(args)
        return buffer.getvalue()
    finally:
        globals()["COLOR_ENABLED"] = previous


def limit_local_usage_days(local_data: Any, days: int) -> None:
    if not isinstance(local_data, dict) or days < 1:
        return
    sessions = local_data.get("sessions")
    if not isinstance(sessions, dict):
        return
    daily_usage = sessions.get("daily_usage")
    if isinstance(daily_usage, list):
        sessions["daily_usage"] = daily_usage[-days:]


def export_json(report: str, top: int, days: int) -> Any:
    if report == "resets":
        return collect_resets()
    if report == "local-usage":
        data = collect_local_usage(CODEX_HOME, top_n=top)
        limit_local_usage_days(data, days)
        return data
    if report == "online-usage":
        return collect_online_usage()
    data = collect_all(top)
    limit_local_usage_days(data.get("local_usage"), days)
    return data


def rows_for_csv(report: str, data: Any, top: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if report in {"resets", "all"}:
        reset_data = data if report == "resets" else data.get("reset_credits", {})
        for credit in reset_data.get("credits", []):
            rows.append({"section": "reset_credit", **credit})
    if report in {"local-usage", "all"}:
        local = data if report == "local-usage" else data.get("local_usage", {})
        sessions = local.get("sessions", {})
        for row in sessions.get("daily_usage", []):
            rows.append({"section": "daily_local_usage", **row})
        selected = local.get("sqlite_threads", {}).get("selected") or {}
        for row in selected.get("by_model", [])[:top]:
            rows.append({"section": "sqlite_model_usage", **row})
    if report in {"online-usage", "all"}:
        online = data if report == "online-usage" else data.get("online_usage", {})
        for name, item in online.get("endpoints", {}).items():
            rows.append({"section": "online_endpoint", "name": name, "path": item.get("path"), "ok": item.get("ok"), "status": item.get("status")})
            if item.get("ok"):
                for path, value in flatten_interesting(item.get("data"), limit=top):
                    rows.append({"section": "online_field", "name": name, "field": path, "value": value})
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys or ["section"])
        writer.writeheader()
        writer.writerows(rows)


def export_path(report: str, fmt: str) -> Path:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S_%f")
    path = EXPORT_DIR / f"codex_{report}_report_{timestamp}.{fmt}"
    counter = 1
    while path.exists():
        path = EXPORT_DIR / f"codex_{report}_report_{timestamp}_{counter}.{fmt}"
        counter += 1
    return path


def export_report(report: str, fmt: str, top: int, days: int, warn_days: int) -> Path:
    path = export_path(report, fmt)
    if fmt == "json":
        data = export_json(report, top, days)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False))
            handle.write("\n")
    elif fmt == "csv":
        data = export_json(report, top, days)
        write_csv(path, rows_for_csv(report, data, top=top))
    elif fmt == "txt":
        args = argparse.Namespace(json=False, top=top, days=days, warn_days=warn_days, colour="never")
        funcs = {"all": cmd_all, "resets": cmd_resets, "local-usage": cmd_local_usage, "online-usage": cmd_online_usage}
        text = render_text(funcs[report], args)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    else:
        die(f"Unsupported export format: {fmt}")
    return path


def cmd_export(args: argparse.Namespace) -> None:
    set_colour_mode(getattr(args, "colour", None))
    path = export_report(args.report, args.format, args.top, args.days, args.warn_days)
    print(f"Exported {args.report} report to: {path}")




def menu_clear() -> None:
    if sys.stdout.isatty():
        os.system("clear")


def menu_box_width(title: str, lines: list[str]) -> int:
    return max([display_width(title), *(display_width(line) for line in lines), 28]) + 4


def centre_display(value: str, width: int) -> str:
    value_width = display_width(value)
    left = max(0, (width - value_width) // 2)
    right = max(0, width - value_width - left)
    return " " * left + value + " " * right


def menu_box(title: str, lines: list[str], width: int | None = None) -> None:
    width = width or menu_box_width(title, lines)
    print("┌" + "─" * width + "┐")
    print("│" + centre_display(title, width) + "│")
    print("├" + "─" * width + "┤")
    for line in lines:
        print("│  " + pad_display(line, width - 2) + "│")
    print("└" + "─" * width + "┘")


def menu_read_choice(prompt: str = "Choose an option: ") -> str:
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "q"


def after_report(action: Callable[[], None]) -> str:
    if not sys.stdin.isatty():
        return "menu"
    while True:
        choice = menu_read_choice("\n[r] Refresh  [m] Menu  [q] Quit: ")
        if choice in {"r", "refresh"}:
            menu_clear()
            action()
            continue
        if choice in {"m", "menu", ""}:
            return "menu"
        if choice in {"q", "quit", "exit"}:
            return "quit"
        print("Please choose r, m, or q.")



def menu_show_settings_help(top: int, days: int, warn_days: int) -> None:
    menu_clear()
    section("Display Settings")
    print("These settings only affect how much information the menu shows during this")
    print("run. They do not change Codex, your account, ~/.codex, or any server setting.")
    print()
    print_kv("Current top", top)
    print("  top controls ranked-table length. Examples:")
    print("    • Top sessions by total tokens")
    print("    • Tokens by model")
    print("    • Technical details fields for online endpoints")
    print("  Use a small number such as 5 for compact output, or 20+ for deeper review.")
    print("  In online reports this also limits Technical details field samples.")
    print()
    print_kv("Current days", days)
    print("  days controls how many recent calendar days appear in local daily-usage")
    print("  tables. It does not delete or ignore older data; it only limits display.")
    print()
    print_kv("Current warn_days", warn_days)
    print("  warn_days controls reset-credit expiry warnings. If a reset expires within")
    print("  this many days, the reset report shows a warning. Use 0 to disable these")
    print("  soon-expiry warnings. Expired credits still show their status if returned.")
    print()
    print("Press Enter at a prompt to keep the current value.")


def cmd_menu(args: argparse.Namespace) -> None:
    set_colour_mode(getattr(args, "colour", None))
    top = args.top
    days = args.days
    warn_days = args.warn_days
    quick_summary: dict[str, Any] | None = None
    quick_summary_error: str | None = None
    while True:
        menu_clear()
        if quick_summary is None and quick_summary_error is None:
            try:
                quick_summary = collect_quick_summary()
            except Exception as exc:
                quick_summary_error = f"Quick summary unavailable: {type(exc).__name__}: {exc}"
        menu_lines = [
            "1) Show everything (resets + local + online)",
            "2) Show reset credits only",
            "3) Show local usage only (no network calls)",
            "4) Show online usage/profile (GET only)",
            "5) Export report",
            f"6) Settings (top={top}, days={days}, warn_days={warn_days})",
            "7) Refresh quick summary",
            "q) Quit",
        ]
        quick_lines = quick_summary_lines(quick_summary) if quick_summary is not None else [quick_summary_error or "Quick summary unavailable"]
        box_width = max(menu_box_width("Quick Summary", quick_lines), menu_box_width("Codex Usage", menu_lines))
        menu_box("Quick Summary", quick_lines, width=box_width)
        print()
        menu_box("Codex Usage", menu_lines, width=box_width)
        choice = menu_read_choice()
        if choice in {"1", "a", "all"}:
            def action() -> None:
                cmd_all(argparse.Namespace(json=False, top=top, days=days, warn_days=warn_days, colour=None))
            menu_clear(); action()
            if after_report(action) == "quit": return
        elif choice in {"2", "r", "resets", "reset"}:
            def action() -> None:
                cmd_resets(argparse.Namespace(json=False, warn_days=warn_days, colour=None))
            menu_clear(); action()
            if after_report(action) == "quit": return
        elif choice in {"3", "l", "local", "local-usage", "usage"}:
            def action() -> None:
                cmd_local_usage(argparse.Namespace(json=False, top=top, days=days, colour=None))
            menu_clear(); action()
            if after_report(action) == "quit": return
        elif choice in {"4", "o", "online", "online-usage"}:
            def action() -> None:
                cmd_online_usage(argparse.Namespace(json=False, top=top, colour=None))
            menu_clear(); action()
            if after_report(action) == "quit": return
        elif choice in {"5", "e", "export"}:
            report = menu_read_choice("Report [all/resets/local-usage/online-usage] (default all): ") or "all"
            fmt = menu_read_choice("Format [txt/json/csv] (default txt): ") or "txt"
            if report not in {"all", "resets", "local-usage", "online-usage"} or fmt not in {"txt", "json", "csv"}:
                print("Invalid report or format.")
                quick_summary = None
                quick_summary_error = None
                continue
            path = export_report(report, fmt, top, days, warn_days)
            print(f"Exported to: {path}")
            quick_summary = None
            quick_summary_error = None
            continue
        elif choice in {"6", "s", "settings"}:
            menu_show_settings_help(top, days, warn_days)
            new_top = menu_read_choice("\nNew top row limit (blank keeps current): ")
            new_days = menu_read_choice("New daily-history day count (blank keeps current): ")
            new_warn = menu_read_choice("New reset-expiry warning window in days (0 disables; blank keeps current): ")
            try:
                if new_top: top = max(1, int(new_top))
                if new_days: days = max(1, int(new_days))
                if new_warn: warn_days = max(0, int(new_warn))
                print()
                print("Updated display settings for this menu session:")
                print_kv("top rows", top)
                print_kv("daily-history days", days)
                print_kv("reset warning days", warn_days)
                if after_report(lambda: menu_show_settings_help(top, days, warn_days)) == "quit": return
            except ValueError:
                print("Please enter whole numbers, e.g. 10, 30, or 7.")
                after_report(lambda: menu_show_settings_help(top, days, warn_days))
        elif choice in {"7", "refresh-summary", "summary"}:
            quick_summary = None
            quick_summary_error = None
            continue
        elif choice in {"q", "quit", "exit"}:
            print("Bye.")
            return
        else:
            print(f"Unknown option: {choice or '(blank)'}")
            after_report(lambda: None)




def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return number


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--colour", "--color", choices=["auto", "always", "never"], default="auto", help="Colour output: auto, always, never. Default: auto.")
    parser.add_argument("--no-colour", "--no-color", action="store_const", const="never", dest="colour", help="Disable colour output.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show Codex reset credits, local usage metadata, and read-only online usage/profile data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              ./codex_usage.py
              ./codex_usage.py resets --warn-days 14
              ./codex_usage.py local-usage --top 20 --days 60
              ./codex_usage.py online-usage --top 5 --no-colour
              ./codex_usage.py export --report all --format txt

            Run './codex_usage.py <command> --help' for command-specific switches.
        """),
    )
    subparsers = parser.add_subparsers(dest="command")

    all_reports = subparsers.add_parser("all", help="Show everything: reset credits, local usage, and online usage/profile.")
    add_common(all_reports)
    all_reports.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    all_reports.add_argument("--top", type=positive_int, default=10, help="Number of top rows to show. Must be at least 1. Default: 10.")
    all_reports.add_argument("--days", type=positive_int, default=30, help="Number of recent daily rows to show. Must be at least 1. Default: 30.")
    all_reports.add_argument("--warn-days", type=non_negative_int, default=7, help="Warn when reset credits expire within this many days. Use 0 to disable soon-expiry warnings. Default: 7.")
    all_reports.set_defaults(func=cmd_all)

    menu = subparsers.add_parser("menu", help="Open the interactive TUI-style menu.")
    add_common(menu)
    menu.add_argument("--top", type=positive_int, default=10, help="Number of top rows to show. Must be at least 1. Default: 10.")
    menu.add_argument("--days", type=positive_int, default=30, help="Number of recent daily rows to show. Must be at least 1. Default: 30.")
    menu.add_argument("--warn-days", type=non_negative_int, default=7, help="Warn when reset credits expire within this many days. Use 0 to disable soon-expiry warnings. Default: 7.")
    menu.set_defaults(func=cmd_menu)

    resets = subparsers.add_parser("resets", help="Show online Codex reset credits only.")
    add_common(resets)
    resets.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    resets.add_argument("--warn-days", type=non_negative_int, default=7, help="Warn when reset credits expire within this many days. Use 0 to disable soon-expiry warnings. Default: 7.")
    resets.set_defaults(func=cmd_resets)

    local_usage = subparsers.add_parser("local-usage", help="Show local-only Codex usage metadata. Makes no network calls.")
    add_common(local_usage)
    local_usage.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    local_usage.add_argument("--top", type=positive_int, default=10, help="Number of top rows to show. Must be at least 1. Default: 10.")
    local_usage.add_argument("--days", type=positive_int, default=30, help="Number of recent daily rows to show. Must be at least 1. Default: 30.")
    local_usage.set_defaults(func=cmd_local_usage)

    online_usage = subparsers.add_parser("online-usage", help="Show read-only online usage/profile data from undocumented GET endpoints.")
    add_common(online_usage)
    online_usage.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    online_usage.add_argument("--top", type=positive_int, default=30, help="Number of Technical details fields to show per endpoint. Must be at least 1. Default: 30.")
    online_usage.set_defaults(func=cmd_online_usage)

    export = subparsers.add_parser("export", help="Export a report next to this script as TXT, JSON, or CSV.")
    add_common(export)
    export.add_argument("--report", choices=["all", "resets", "local-usage", "online-usage"], default="all", help="Report to export. Default: all.")
    export.add_argument("--format", choices=["txt", "json", "csv"], default="txt", help="Export format. Default: txt.")
    export.add_argument("--top", type=positive_int, default=10, help="Number of top rows to include. Must be at least 1. Default: 10.")
    export.add_argument("--days", type=positive_int, default=30, help="Number of recent daily rows to include. Must be at least 1. Default: 30.")
    export.add_argument("--warn-days", type=non_negative_int, default=7, help="Warn when reset credits expire within this many days. Use 0 to disable soon-expiry warnings. Default: 7.")
    export.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        default_command = "menu" if sys.stdin.isatty() and sys.stdout.isatty() else "all"
        args = parser.parse_args([default_command] + (argv or []))
    args.func(args)


if __name__ == "__main__":
    main()
