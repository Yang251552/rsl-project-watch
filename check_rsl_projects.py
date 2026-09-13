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
# A detection this close to the read waits for the next day's read: covers job runtime, git push
# and the raw.githubusercontent.com cache (max-age=300), so a read never misses an item dated today.
MARGIN = datetime.timedelta(minutes=20)
FIELDS = ("url", "title", "date", "desc", "push_date")
SURROGATES = re.compile(r"[\ud800-\udfff]")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _s(value):
    # json.loads keeps lone UTF-16 surrogates (a pair split upstream); they crash print and the
    # UTF-8 json.dump, so drop them here at the trust boundary.
    return SURROGATES.sub("", value or "").strip()


def _clean(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _s(html))).strip()


def parse(raw):
    out = {}
    for e in raw:
        url = _s(e.get("url"))
        if not url or url in out:  # url is the identity; keep the first of any duplicates
            continue
        out[url] = {
            "url": url,
            "title": re.sub(r"\s+", " ", _s(e.get("title"))),
            "date": _s(e.get("dateFormatted")),
            "desc": _clean(e.get("description"))[:220],
        }
    return list(out.values())


def diff_new(old_urls, entries):
    """New entries = url not seen before. old_urls is None on the first ever run."""
    if old_urls is None:
        return None  # first-run sentinel
    return [e for e in entries if e["url"] not in old_urls]


def push_date(detected_at):
    """Local date (ISO) of the first PUSH_HOUR read sure to see a detection made at detected_at."""
    day = (detected_at + MARGIN - datetime.timedelta(hours=PUSH_HOUR)).date()
    return (day + datetime.timedelta(days=1)).isoformat()


def merge(pending, found):
    urls = {e["url"] for e in pending}
    return pending + [e for e in found if e["url"] not in urls]


def carry(items, today):
    """Published detections whose read may still be ahead (push_date >= today). Carrying them into
    every run means a re-run or a late cron extends the list instead of wiping what's unread."""
    try:
        return [e for e in items if isinstance(e, dict)
                and all(isinstance(e.get(k), str) for k in FIELDS) and e["push_date"] >= today]
    except TypeError:  # items is not a list at all
        return []


def load_pending(today):
    try:
        with open(LATEST, encoding="utf-8") as f:
            return carry(json.load(f)["new"], today)
    except (OSError, ValueError, KeyError, TypeError):
        return []


def load_state():
    # Missing, unreadable OR structurally wrong snapshot -> None (first-run / self-healing
    # reseed), never a crash that would swallow the whole report.
    # Returns {url: title} so removals can be logged with a readable name.
    try:
        with open(STATE, encoding="utf-8") as f:
            seen = json.load(f).get("seen")
    except (OSError, ValueError, AttributeError):
        return None
    return seen if isinstance(seen, dict) else None


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
    """Return True on success. A write failure is non-fatal: the report is already out."""
    try:
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
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump({"run_at": run_at.isoformat(timespec="seconds"), "status": status,
                   "listed": listed, "new": new, "error": error},
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
    assert merge(es[:1], es) == es               # a re-detected pending item is not duplicated
    cest = datetime.timezone(datetime.timedelta(hours=2))
    at = lambda day, hour, minute=0: datetime.datetime(2026, 9, day, hour, minute, tzinfo=cest)
    assert push_date(at(14, 5, 23)) == "2026-09-14"   # scheduled run: that morning's read
    assert push_date(at(14, 6, 39)) == "2026-09-14"   # still published and past the raw cache by 07:00
    assert push_date(at(14, 6, 40)) == "2026-09-15"   # too close to the read: next morning
    assert push_date(at(13, 12)) == "2026-09-14"      # daytime run: next morning
    read, unread = dict(es[0], push_date="2026-09-13"), dict(es[1], push_date="2026-09-14")
    assert carry([read, unread, {"url": "x"}, None], "2026-09-14") == [unread]  # already read / malformed
    assert carry(None, "2026-09-14") == []
    feed = [{"url": "u", "title": "T\ud83d\n x "}, {"url": "u", "title": "dup"}]
    assert [e["title"] for e in parse(feed)] == ["T x"]  # lone surrogate dropped, duplicate url dropped
    print("selftest ok")


def main():
    if "--selftest" in sys.argv:
        return selftest()
    run_at = datetime.datetime.now().astimezone()  # TZ from env; the workflow pins Europe/Zurich
    pending = load_pending(run_at.date().isoformat())
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
    if new is None:
        print(f"BASELINE: first run, now tracking {len(entries)} current projects (not reported as new):\n{fmt(entries)}")
        publish(run_at, "BASELINE", pending, len(entries))
    else:
        if new:
            print(f"NEW ({len(new)}) of {len(entries)} listed — {PAGE_URL}\n{fmt(new)}")
        else:
            print(f"NONE: no new projects since last check ({len(entries)} currently listed).")
        found = [dict(e, push_date=push_date(run_at)) for e in new]
        publish(run_at, "NEW" if new else "NONE", merge(pending, found), len(entries))
    # History and snapshot only after publishing: if anything above dies, the next run
    # re-detects these projects instead of finding them already marked seen but never published.
    if old is not None:
        ts = run_at.isoformat(timespec="seconds")
        cur = {e["url"] for e in entries}
        append_history(
            [{"ts": ts, "event": "removed", "url": u, "title": t}
             for u, t in old.items() if u not in cur]
            + [{"ts": ts, "event": "new", "url": e["url"], "title": e["title"],
                "date": e["date"]} for e in new]
        )
    if not save_state(entries, run_at):
        print("WARN: snapshot not saved (write failed); tomorrow may re-report these as new.")


if __name__ == "__main__":
    main()
