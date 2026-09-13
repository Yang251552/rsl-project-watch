#!/usr/bin/env python3
"""Daily check of ETH RSL available student projects — GitHub Actions edition.

Fetches the page's own JSON feed, diffs it against state/seen.json, and writes the
outcome to state/latest_run.json, which the 07:00 Cowork task reads through
raw.githubusercontent.com (Cowork itself can't reach rsl.ethz.ch). The snapshot is
overwritten ONLY on a successful, non-empty fetch, so a network blip or endpoint
change can't flood the next run with false "new" entries.

    python3 check_rsl_projects.py            # run the check (mutates state/)
    python3 check_rsl_projects.py --selftest # run the logic self-check
"""
import datetime
import json
import os
import re
import sys
import urllib.request

FEED_URL = "https://rsl.ethz.ch/education-students/student-projects0/available-projects/_jcr_content/par/rssreader.rssfeed.json"
PAGE_URL = "https://rsl.ethz.ch/education-students/student-projects0/available-projects.html"
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
STATE = os.path.join(STATE_DIR, "seen.json")
HISTORY = os.path.join(STATE_DIR, "history.jsonl")
LATEST = os.path.join(STATE_DIR, "latest_run.json")
PUSH_HOUR = 7  # local hour the Cowork task reads LATEST; keep in sync with its schedule


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _clean(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def parse(raw):
    out = []
    for e in raw:
        url = (e.get("url") or "").strip()
        if not url:
            continue
        out.append({
            "url": url,
            "title": re.sub(r"\s+", " ", (e.get("title") or "").strip()),
            "date": (e.get("dateFormatted") or "").strip(),
            "desc": _clean(e.get("description"))[:220],
        })
    return out


def diff_new(old_urls, entries):
    """New entries = url not seen before. old_urls is None on the first ever run."""
    if old_urls is None:
        return None  # first-run sentinel
    return [e for e in entries if e["url"] not in old_urls]


def push_date(run_at):
    """Date of the next PUSH_HOUR:00 read after run_at."""
    return (run_at - datetime.timedelta(hours=PUSH_HOUR)).date() + datetime.timedelta(days=1)


def merge(pending, new):
    urls = {e["url"] for e in pending}
    return pending + [e for e in new if e["url"] not in urls]


def load_pending(run_at):
    """`new` already published for the same read. A second run before that read (manual
    dispatch, or a cron delayed past PUSH_HOUR) extends the list instead of wiping it."""
    try:
        with open(LATEST, encoding="utf-8") as f:
            prev = json.load(f)
        if prev["push_date"] == push_date(run_at).isoformat():
            return prev["new"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return []


def load_state():
    # Missing OR unreadable snapshot -> None (first-run / self-healing reseed),
    # never a crash that would swallow the whole report.
    # Returns {url: title} so removals can be logged with a readable name.
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f).get("seen", {})
    except (FileNotFoundError, ValueError, OSError):
        return None


def append_history(events):
    """Append-only event log (new/removed, with publish dates). Best-effort:
    a write failure never breaks the daily report."""
    if not events:
        return
    try:
        with open(HISTORY, "a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except OSError:
        pass


def save_state(entries, run_at):
    """Return True on success. A write failure is non-fatal: the report still prints."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        data = {
            "updated": run_at.isoformat(timespec="seconds"),
            "seen": {e["url"]: e["title"] for e in entries},
        }
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False


def publish(run_at, status, new, listed=None, error=None):
    """Write LATEST, the contract the Cowork task reads (fields documented in README)."""
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump({"run_at": run_at.isoformat(timespec="seconds"),
                   "push_date": push_date(run_at).isoformat(),
                   "status": status, "listed": listed, "new": new, "error": error},
                  f, ensure_ascii=False, indent=1)


def fmt(entries):
    return "\n".join(f"• {e['title']}  [{e['date']}]\n  {e['url']}\n  {e['desc']}" for e in entries)


def selftest():
    es = [{"url": "a", "title": "A", "date": "", "desc": ""},
          {"url": "b", "title": "B", "date": "", "desc": ""}]
    assert diff_new(None, es) is None            # first run
    assert diff_new(set(), es) == es             # empty snapshot -> all new
    assert diff_new({"a"}, es) == es[1:]         # only b is new
    assert diff_new({"a", "b"}, es) == []        # nothing new
    assert merge(es[:1], es) == es               # re-run before the read extends, never duplicates
    cest = datetime.timezone(datetime.timedelta(hours=2))
    at = lambda day, hour: datetime.datetime(2026, 9, day, hour, 0, 1, tzinfo=cest)
    assert push_date(at(14, 5)) == datetime.date(2026, 9, 14)   # scheduled run feeds that morning's read
    assert push_date(at(13, 12)) == datetime.date(2026, 9, 14)  # run after the read waits for the next one
    assert push_date(at(14, 7)) == datetime.date(2026, 9, 15)   # 07:00:01 just missed the read
    print("selftest ok")


def main():
    if "--selftest" in sys.argv:
        return selftest()
    run_at = datetime.datetime.now().astimezone()  # TZ from env; the workflow pins Europe/Zurich
    pending = load_pending(run_at)
    try:
        entries = parse(fetch(FEED_URL))
    except Exception as ex:
        print(f"FETCH_FAILED: {ex}\nPage: {PAGE_URL}")
        publish(run_at, "FETCH_FAILED", pending, error=str(ex))
        sys.exit(1)
    if not entries:
        # ponytail: treat an empty feed as suspect (endpoint change / soft failure),
        # not as "all positions filled" -> leave snapshot untouched.
        print(f"SUSPECT_EMPTY: feed returned 0 projects; snapshot left unchanged.\nPage: {PAGE_URL}")
        publish(run_at, "SUSPECT_EMPTY", pending)
        sys.exit(2)
    old = load_state()
    new = diff_new(old, entries)
    if old is not None:
        ts = run_at.isoformat(timespec="seconds")
        cur = {e["url"] for e in entries}
        append_history(
            [{"ts": ts, "event": "removed", "url": u, "title": t}
             for u, t in old.items() if u not in cur]
            + [{"ts": ts, "event": "new", "url": e["url"], "title": e["title"],
                "date": e["date"]} for e in new]
        )
    saved = save_state(entries, run_at)
    if new is None:
        print(f"BASELINE: first run, now tracking {len(entries)} current projects (not reported as new):\n{fmt(entries)}")
        publish(run_at, "BASELINE", pending, len(entries))
    else:
        pending = merge(pending, new)
        if pending:
            print(f"NEW ({len(pending)}) of {len(entries)} listed — {PAGE_URL}\n{fmt(pending)}")
        else:
            print(f"NONE: no new projects since last check ({len(entries)} currently listed).")
        publish(run_at, "NEW" if pending else "NONE", pending, len(entries))
    if not saved:
        print("WARN: snapshot not saved (write failed); tomorrow may re-report these as new.")


if __name__ == "__main__":
    main()
