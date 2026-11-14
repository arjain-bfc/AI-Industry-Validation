"""Phase 1: download each account's website into the crawl store, one line per account.

  run()         crawl every account in an input file that needs it
  load_store()  read the crawl store (Phase 2 reads it too)
  compact()     rewrite the store with one line per account
  summary()     one row per stored account: how its crawl went

How a run works. The websites are split between several worker processes (crawl_worker.py), which download them in
up to three passes: a fast plain download for every site, a real browser for the sites that refused or gave back
next to nothing, and a last try with an "undetected" browser for those still refused. This file hands out the work,
saves each account the moment its site is finished, and passes the unfinished sites on to the next pass. A website
shared by several accounts is crawled once.

Which accounts a run crawls is decided in CrawlRun.needs_crawl: new accounts, accounts whose CRM web address
changed, and sites that may work this time (they refused us, didn't answer, or showed a placeholder). Sites that
can't come back (a domain that doesn't exist, a parked domain) are not tried again. Links that aren't a company
website at all (accounts.py) are stored without a crawl.

Stopping and re-running is always safe: saved accounts are skipped.

Around this file: accounts.py reads the input file, crawl_worker.py does the downloading, site_checks.py tells a
real business website from a parked, dead or blocked one.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from accounts import is_listing_link, load_accounts, site_key


FOLDER = Path(__file__).parent


JOBS = FOLDER / "_crawl_jobs"  # the workers' job files, results and logs while a run is going


# --- Settings ------------------------------------------------------------------------------------------------------
# What every worker gets
CRAWL = {
    "max_pages": 40,               # pages per site, plain download: home page first, then the most useful pages
    "max_pages_browser": 20,       # pages per site, browser (40 changed no answer on 20 test sites, and took twice
                                   #   as long)
    "max_depth": 3,                # how many links away from the home page we go
    "site_timeout": 150,           # seconds per site per pass (doubled on the last pass); pages fetched by then kept
    "http_timeout_s": 15,          # seconds per page, plain download
    "browser_page_timeout_s": 30,  # seconds per page, browser (doubled on the last pass)
    "stop_after_timeouts": 4,      # this many pages in a row time out: stop the site, keep what we have
    "http_sites_per_worker": 6,    # sites each plain-download worker fetches at once
    "pages_at_once": 3,            # pages of one site at once, plain download (polite to small sites)
    "browser_pages_at_once": 4,    # pages of one site at once, browser
    "thin_words": 150,             # one page with fewer words than this: try the browser (often a JavaScript site)
    "challenge_wait_s": 20,        # how long the browser waits for a "checking your browser" page (doubled last)
    "bot_check_wait_s": 6,         # a bot-check page is loaded once more after this many seconds
    "restart_browser_every": 50,   # browsers restart every 50 sites (memory)
}


PASSES = [("http", "Pass 1 (plain download)", 8),          # (mode, name, worker processes)
          ("browser", "Pass 2 (browser)", 8),
          ("browser_hard", "Pass 3 (undetected browser)", 2)]


NEXT_PASS = {"needs_browser": "browser", "needs_retry_pass": "browser_hard"}  # what a worker says -> next pass


# Trying again. A site that refused us or didn't answer is usually only down for a while: the run waits a minute and
# tries it again, up to MAX_ATTEMPTS times, and every later run tries it again too. A dead site is tried again on every
# run as well, unless the domain itself is gone: a "coming soon" page or a home page giving a 404 may work a few
# months later; a domain that doesn't exist, or that a host says isn't set up anywhere, won't. Parked and for-sale
# domains aren't tried again either.
TRY_AGAIN = ("unreachable", "blocked")


MAX_ATTEMPTS = 3          # tries within one run


RETRY_WAIT_MIN = 1        # minutes between those tries


DEAD_FOR_GOOD = ("dns_not_found", "host_error")


STOP_AFTER_FAILURES = 10  # this many unreachable sites in a row stops the run (usually our own network is down)


# Input Excel column -> company detail the model sees. The industry_types column (ZoomInfo or CRM label) is kept
# for the report only; it is never shown to the model.
COMPANY_COLUMNS = {"name": "name", "doing_business_as": "doing_business_as", "address_composite": "location"}


def store_record(excel_row, row, status, pages=(), error=None, attempts=1, seconds=0.0, reason=None):
    """One account's line in the crawl store. "final" means no more tries this run; Phase 2 reads final ones only."""
    return {"account_id": row["account_id"], "excel_row": int(excel_row), "url": row["url"],
            "status": status, "reason": reason,
            "final": status not in TRY_AGAIN or attempts >= MAX_ATTEMPTS,
            "error": error, "attempts": attempts, "seconds": round(seconds, 1),
            "crawled_at": datetime.now().isoformat(timespec="seconds"),
            "company": {field: row[col] for col, field in COMPANY_COLUMNS.items() if row.get(col)},
            "reference": {"industry_types": row.get("industry_types", "")},
            "pages": list(pages)}


def may_come_back(record):
    """Whether a finished crawl is worth trying again on the next run, at the same web address: it refused us or
    didn't answer, it was a dead site that may come back (not DEAD_FOR_GOOD), a bot check kept us to its home page
    (partial_bot_check: tried again gently), or its link was skipped as a listing and the list no longer covers it
    (a company's own Facebook or Instagram page, crawled since 2026-11-12)."""
    if record.get("reason") == "partial_bot_check":
        return True
    if record["status"] == "social_media_page_only":
        return not is_listing_link(record["url"])
    if record["status"] == "dead_site":
        return record.get("reason") not in DEAD_FOR_GOOD
    return record["status"] in TRY_AGAIN


# --- The crawl store --------------------------------------------------------------------------------------------------
# One JSON line per account: the account (id, CRM details, website), how its crawl went (status, reason, error) and
# every page fetched (full text, image labels and link tooltips). When an account is crawled or checked again a new
# line is added; the latest line wins. Lines are forced to disk as they are written, so a crash never loses a
# finished account. Phase 2 reads the store and writes back one thing: the result of its website check (mark_site).
def load_store(path):
    """{account_id: latest record}. A line cut off by a crash is skipped."""
    records = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    records[record["account_id"]] = record
                except json.JSONDecodeError:
                    pass
    return records


def append_line(path, obj):
    """Append one JSON line and force it to disk."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def compact(path):
    """Rewrite the store with one line per account (re-crawls and website checks add lines). Returns the count."""
    records = load_store(path)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for record in records.values():
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return len(records)


def mark_site(path, record, status, by, score=None):
    """Phase 2's website check: save the account again as "wrong_site", shown as a "website issue" (Phase 2 skips it;
    Phase 1 crawls it again once the CRM web address changes, or with recheck_website_issues) or back to "ok".
    by="manual" means a person said the site is the company's: it is never checked again. Returns the new record."""
    new = {**record, "status": status, "final": True,
           "site_check": {"status": status, "score": score, "by": by, "url": record["url"],
                          "at": datetime.now().isoformat(timespec="seconds")}}
    append_line(path, new)
    return new


def cleared_by_hand(record):
    """True when a person said this website is the company's."""
    check = record.get("site_check") or {}
    return check.get("by") == "manual" and check.get("status") == "ok"


# --- One crawl run -------------------------------------------------------------------------------------------------
class CrawlRun:
    """Keeps track of one run: decides which accounts to crawl, saves each finished site to the store, and collects
    the sites for the next pass."""

    def __init__(self, store_path, recrawl, started=None):
        self.store_path, self.recrawl = store_path, recrawl
        self.started = started or datetime.now().isoformat(timespec="seconds")  # when this run (crawl.run) began
        self.store = load_store(store_path)
        wrong_sites = {site_key(r["url"]) for r in self.store.values() if r["status"] == "wrong_site"}
        # Websites already crawled for another account: copied, not crawled again. Not a crawl that is due for
        # another try itself (may_come_back: a bot check kept us to its home page)
        self.crawled = {site_key(r["url"]): r for r in self.store.values()
                        if r["status"] == "ok" and site_key(r["url"]) not in wrong_sites and not may_come_back(r)}
        self.next_pass = {"browser": [], "browser_hard": []}
        self.saved, self.total, self.unreachable_in_a_row = 0, 0, 0

    def needs_crawl(self, account_id, url):
        """Whether to crawl this account now: it has never been crawled, it is in RECRAWL_IDS, it has tries left
        in this run, the CRM has a different web address from the one stored, or its last result may be different
        this time (may_come_back). Not crawled: finished sites, parked domains and domains that are gone, and wrong
        websites or listing links still in the CRM unchanged."""
        rec = self.store.get(account_id)
        if rec is None or account_id in self.recrawl or not rec["final"]:
            return True
        return site_key(url) != site_key(rec["url"]) or may_come_back(rec)

    def save(self, record):
        """Write one account to the store and print a line about it. One exception: when an account was crawled
        again on purpose (RECRAWL_IDS) and this time it failed, the earlier good crawl is kept instead."""
        previous = self.store.get(record["account_id"])
        self.saved += 1
        if (record["account_id"] in self.recrawl and previous and previous["status"] == "ok"
                and record["status"] != "ok" and record["url"] == previous["url"]):
            print(f"[{self.saved}/{self.total}] {record['url']}: re-crawl failed, kept the earlier crawl")
            return
        append_line(self.store_path, record)
        self.store[record["account_id"]] = record
        if record["status"] == "ok" and not may_come_back(record):
            self.crawled[site_key(record["url"])] = record
        self.unreachable_in_a_row = self.unreachable_in_a_row + 1 if record["status"] == "unreachable" else 0
        reason = f" ({record['reason']})" if record.get("reason") else ""
        print(f"[{self.saved}/{self.total}] {record['url'] or '-'}: {record['status']}{reason}, "
              f"{len(record['pages'])} pages, {record['seconds']}s")

    def save_site(self, site):
        """Save a finished website for every account that has it. The try count goes up by one each time this run
        crawls the account again; it starts again at 1 on a new run, on a new web address, or when the crawl was
        asked for (RECRAWL_IDS)."""
        for account in site["accounts"]:
            row = account["row"]
            previous = self.store.get(row["account_id"])
            first_try = (previous is None or row["account_id"] in self.recrawl
                         or site_key(previous["url"]) != site_key(row["url"])
                         or previous.get("crawled_at", "") < self.started)  # last crawled on an earlier run
            attempts = 1 if first_try else previous["attempts"] + 1
            self.save(store_record(account["excel_row"], row, site["status"], site["pages"], site["error"],
                                   attempts, site["seconds"], site.get("reason")))

    def collect(self, read_up_to):
        """Read what the workers have finished since last time: save each finished site, and set aside the ones
        handed on to the next pass.

        Each worker appends one line per site to its own results file while we read it, every 2 seconds. To read
        only what's new, we remember how far into each file we've read (read_up_to: {results file: bytes read}) and
        start from there. The last line may still be half-written, so we only take up to the last line break; the
        rest is read next time."""
        for results_file in sorted(JOBS.glob("part_*.jsonl")):
            with open(results_file, "rb") as f:
                f.seek(read_up_to.get(results_file, 0))  # jump to where we stopped last time
                new = f.read()
            complete = new[: new.rfind(b"\n") + 1]  # up to and including the last line break
            read_up_to[results_file] = read_up_to.get(results_file, 0) + len(complete)
            # split on line breaks only (not splitlines()): page text can contain unusual Unicode line separators
            for line in complete.decode("utf-8").split("\n"):
                if line.strip():
                    site = json.loads(line)
                    if site["status"] in NEXT_PASS:
                        self.next_pass[NEXT_PASS[site["status"]]].append(site)
                    else:
                        self.save_site(site)

    def run_pass(self, mode, name, workers, sites):
        """Split the sites between worker processes, then save their results as they come in."""
        if not sites:
            return
        n = min(workers, len(sites))
        print(f"\n--- {name}: {len(sites)} websites, {n} workers ---\n")
        clear_jobs()
        processes, read_up_to, start = [], {}, time.perf_counter()
        try:
            for i in range(n):
                job, results, log = JOBS / f"job_{i}.json", JOBS / f"part_{i}.jsonl", JOBS / f"{mode}_worker_{i}.log"
                job.write_text(json.dumps({"mode": mode, "settings": CRAWL, "sites": sites[i::n]}), encoding="utf-8")
                with open(log, "w", encoding="utf-8") as log_file:
                    processes.append((log, subprocess.Popen(
                        [sys.executable, str(FOLDER / "crawl_worker.py"), str(job), str(results)],
                        stdout=log_file, stderr=subprocess.STDOUT)))
            while any(p.poll() is None for _, p in processes):
                self.collect(read_up_to)
                if self.unreachable_in_a_row >= STOP_AFTER_FAILURES:
                    raise RuntimeError(f"{STOP_AFTER_FAILURES} unreachable sites in a row: check the network, "
                                       "then re-run")
                time.sleep(2)
        finally:
            stopped_early = any(p.poll() is None for _, p in processes)
            for _, p in processes:  # stopped early (or by you): end the workers and their browsers
                if p.poll() is None:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
                    else:
                        p.kill()
                p.wait()
            self.collect(read_up_to)
            clear_jobs()
            for log, p in processes:
                if p.returncode != 0 and not stopped_early:
                    print(f"\nA worker failed. The end of {log.name}:\n" +
                          "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]))
            print(f"\n{name} took {(time.perf_counter() - start) / 60:.1f} min")


def clear_jobs():
    for path in [*JOBS.glob("job_*.json"), *JOBS.glob("part_*.jsonl")]:
        path.unlink()


def run(input_xlsx, store_path, limit=None, recrawl_ids=(), retry_wait_min=RETRY_WAIT_MIN,
        recheck_website_issues=False):
    """Crawl every account in input_xlsx that needs it (CrawlRun.needs_crawl), then try again the sites that refused
    us or didn't answer: wait retry_wait_min minutes, crawl only those, and repeat until each has had MAX_ATTEMPTS
    tries (the next run tries them again). retry_wait_min=None: no waiting, leave them for the next run.
    limit: at most this many accounts. recrawl_ids: account_ids to crawl again even though they are stored.
    recheck_website_issues: also crawl again every account whose website failed Phase 2's website check (a "website
    issue"). Off by default: they are not tried again on their own (at 100,000 accounts that would be 2,000-3,000
    sites every run, most of them taken-over, sold or other businesses' sites that won't change); they come back
    when the CRM web address changes, or when this is switched on for an occasional sweep."""
    started = datetime.now().isoformat(timespec="seconds")
    recrawl = {i.lower() for i in recrawl_ids}
    if recheck_website_issues:
        recrawl |= {i.lower() for i, r in load_store(store_path).items() if r["status"] == "wrong_site"}
    unfinished = crawl_round(input_xlsx, store_path, limit, recrawl, started=started)
    while unfinished and retry_wait_min is not None:
        print(f"\n{len(unfinished)} sites refused us or didn't answer: trying them again in {retry_wait_min} min "
              "(stop now to leave them for the next run)")
        time.sleep(retry_wait_min * 60)
        unfinished = crawl_round(input_xlsx, store_path, None, set(), only=unfinished, started=started)


def crawl_round(input_xlsx, store_path, limit, recrawl, only=None, started=None):
    """One go at the accounts that need crawling (or only the account_ids in `only`). Returns the account_ids crawled
    this round that still have tries left."""
    JOBS.mkdir(exist_ok=True)
    crawl_run = CrawlRun(store_path, recrawl, started)
    if any(JOBS.glob("part_*.jsonl")):  # the last run was cut off: keep what its workers had finished
        crawl_run.collect({})
        clear_jobs()

    accounts = load_accounts(input_xlsx)
    todo = [(excel_row, row) for excel_row, row in accounts.iterrows()
            if crawl_run.needs_crawl(row["account_id"], row["url"]) and (only is None or row["account_id"] in only)]
    print(f"{len(accounts)} accounts | {len(accounts) - len(todo)} already stored | {len(todo)} to crawl"
          + (f" | {min(limit, len(todo))} this run" if limit else ""))
    todo = todo[:limit] if limit else todo
    crawl_run.total = len(todo)

    to_crawl = {}  # website (site_key) -> its address and the accounts that have it
    for excel_row, row in todo:
        url = row["url"]
        if not url:
            crawl_run.save(store_record(excel_row, row, "no_website"))
        elif is_listing_link(url):
            crawl_run.save(store_record(excel_row, row, "social_media_page_only"))
        elif site_key(url) in crawl_run.crawled and row["account_id"] not in recrawl:  # crawled for another account
            source = crawl_run.crawled[site_key(url)]
            crawl_run.save(store_record(excel_row, row, "ok", source["pages"], reason=source.get("reason")))
        else:
            site = to_crawl.setdefault(site_key(url), {"url": url, "accounts": [], "gentle": False})
            site["accounts"].append({"excel_row": int(excel_row), "row": row.to_dict()})
            last = crawl_run.store.get(row["account_id"]) or {}
            if last.get("reason") == "partial_bot_check" and site_key(last.get("url")) == site_key(url):
                site["gentle"] = True  # a bot check stopped us last time: one page at a time (crawl_worker.py)

    start = time.perf_counter()
    try:
        sites = list(to_crawl.values())
        for mode, name, workers in PASSES:
            if mode != "http":  # passes 2 and 3 get the sites the pass before handed on
                sites, crawl_run.next_pass[mode] = crawl_run.next_pass[mode], []
            crawl_run.run_pass(mode, name, workers, sites)
    finally:
        print(f"\n{crawl_run.saved} of {len(todo)} saved in {(time.perf_counter() - start) / 60:.1f} min. "
              "Re-run to continue if it stopped.")
    return {row["account_id"] for _, row in todo if not crawl_run.store.get(row["account_id"], {}).get("final", True)}


def summary(store_path, summary_xlsx=None):
    """One row per stored account (without the page text); also saved to summary_xlsx if given."""
    table = pd.DataFrame([{
        "account_id": r["account_id"], "excel_row": r["excel_row"], "name": r["company"].get("name", ""),
        "url": r["url"], "status": r["status"], "reason": r.get("reason"), "final": r["final"],
        "attempts": r["attempts"], "pages": len(r["pages"]), "words": sum(len(p["text"].split()) for p in r["pages"]),
        "error": r["error"], "crawled_at": r["crawled_at"],
    } for r in load_store(store_path).values()]).sort_values("excel_row")
    if summary_xlsx:
        table.to_excel(summary_xlsx, index=False)
    return table
