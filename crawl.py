"""Phase 1: download each account's website into the crawl store, one line per account.

  run()          crawl every account in an input file that needs it
  load_store()   read the crawl store (Phase 2 reads it too); compact() rewrites it with one line per account
  summary()      one row per stored account: how its crawl went
  make_sample()  write a new input file: random accounts with a website, none from earlier sets

How a run works. The websites are split between several worker processes (crawl_worker.py), which download them in
up to three passes: a fast plain download for every site, a real browser for the sites that refused or gave back
next to nothing, and a last try with an "undetected" browser for those still refused. This file hands out the work,
saves each account the moment its site is finished, and passes the unfinished sites on to the next pass.

Stopping and re-running is always safe: saved accounts are skipped. Accounts that share a website are crawled once.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


FOLDER = Path(__file__).parent
JOBS = FOLDER / "_crawl_jobs"  # the workers' job files, results and logs while a run is going

# Settings every worker gets
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

TRY_AGAIN = ("unreachable", "blocked")  # statuses that are tried again on a later run...
MAX_ATTEMPTS = 3                        # ...up to this many times in all
STOP_AFTER_FAILURES = 10  # this many unreachable sites in a row stops the run (usually our own network is down)
SOCIAL_SITES = ("facebook.com", "instagram.com", "linkedin.com", "yelp.com", "x.com", "twitter.com")
# Input Excel column -> company detail the model sees. The industry_types column (ZoomInfo or CRM label) is kept
# for the report only; it is never shown to the model.
COMPANY_COLUMNS = {"name": "name", "doing_business_as": "doing_business_as", "address_composite": "location"}


# --- The crawl store ------------------------------------------------------------------------------------------------
# One JSON line per account: the account (id, CRM details, website), how its crawl went (status, reason, error) and
# every page fetched (full text and image labels). When an account is crawled or checked again a new line is added;
# the latest line wins. Lines are forced to disk as they are written, so a crash never loses a finished account.
# Phase 2 reads the store and writes back one thing: the result of its website check (mark_site).
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


# --- Website check results (set by Phase 2) ----------------------------------------------------------------------
def mark_site(path, record, status, by, score=None):
    """Save the account again as "wrong_site" (Phase 2 skips it; Phase 1 re-crawls it once the CRM URL changes) or
    back to "ok". by="manual" means a person cleared it: it is never checked again. Returns the new record."""
    new = {**record, "status": status, "final": True,
           "site_check": {"status": status, "score": score, "by": by, "url": record["url"],
                          "at": datetime.now().isoformat(timespec="seconds")}}
    append_line(path, new)
    return new


def cleared_by_hand(record):
    """True when a person said this website is the company's."""
    check = record.get("site_check") or {}
    return check.get("by") == "manual" and check.get("status") == "ok"


# --- The accounts --------------------------------------------------------------------------------------------------
def load_accounts(input_xlsx):
    """The input Excel, tidied: one row per account (indexed by its Excel row number), account_id in lower case, the
    website with https:// in front."""
    df = pd.read_excel(input_xlsx, dtype=str).fillna("")
    # CRM exports carry stray carriage returns, line breaks inside cells and the text "NULL" for empty cells
    df = df.replace({r"_x000D_": "", r"\s*\n\s*": ", ", r"^\s*NULL\s*$": ""}, regex=True)
    df = df.apply(lambda column: column.str.strip())
    df.index = df.index + 2  # Excel row numbers: the header is row 1
    df["account_id"] = df["account_id"].str.lower()
    df = df[(df["account_id"] != "") & ~df["account_id"].duplicated()]
    df["url"] = df["company_website"].map(full_address)
    return df


def full_address(website):
    """'acme.com' -> 'https://acme.com'; an empty cell -> None."""
    if not website:
        return None
    return website if website.startswith("http") else "https://" + website


def is_social_page(url):
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == s or host.endswith("." + s) for s in SOCIAL_SITES)


def make_sample(input_xlsx, n, out_xlsx, exclude=(), per_label=False, labels=None, seed=42):
    """Write a new input Excel (same columns) of randomly picked accounts that have a real website.
      exclude    crawl stores (.jsonl) or input files (.xlsx) whose accounts must not be picked, so sets never overlap
      per_label  True: n accounts for each industry_types label (all of a label that has fewer); False: n in total
      labels     only these industry_types labels, e.g. the five segments"""
    raw = pd.read_excel(input_xlsx, dtype=str)
    accounts = load_accounts(input_xlsx)
    used = set()
    for path in map(Path, exclude):
        used |= set(load_store(path)) if path.suffix == ".jsonl" else set(load_accounts(path)["account_id"])
    candidates = accounts[accounts["url"].notna() & ~accounts["url"].fillna("").map(is_social_page)
                          & ~accounts["account_id"].isin(used)]
    if labels:
        candidates = candidates[candidates["industry_types"].isin(labels)]
    groups = [group for _, group in candidates.groupby("industry_types")] if per_label else [candidates]
    picked = pd.concat([g.sample(min(n, len(g)), random_state=seed) for g in groups]).sort_index()
    raw.loc[picked.index - 2].to_excel(out_xlsx, index=False)
    print(f"{len(picked)} of {len(candidates)} fresh accounts with a website -> {Path(out_xlsx).name}")
    print(picked["industry_types"].value_counts().to_string())


def store_record(excel_row, row, status, pages=(), error=None, attempts=1, seconds=0.0, reason=None):
    """One account's line in the crawl store."""
    return {"account_id": row["account_id"], "excel_row": int(excel_row), "url": row["url"],
            "status": status, "reason": reason,
            "final": status not in TRY_AGAIN or attempts >= MAX_ATTEMPTS,  # Phase 2 reads final records only
            "error": error, "attempts": attempts, "seconds": round(seconds, 1),
            "crawled_at": datetime.now().isoformat(timespec="seconds"),
            "company": {field: row[col] for col, field in COMPANY_COLUMNS.items() if row.get(col)},
            "reference": {"industry_types": row.get("industry_types", "")},
            "pages": list(pages)}


# --- One crawl run -------------------------------------------------------------------------------------------------
class CrawlRun:
    """Keeps track of one run: saves each finished site to the store, and collects the sites for the next pass."""

    def __init__(self, store_path, recrawl):
        self.store_path, self.recrawl = store_path, recrawl
        self.store = load_store(store_path)
        wrong_sites = {r["url"] for r in self.store.values() if r["status"] == "wrong_site"}
        # Websites already crawled for another account: copied, not crawled again
        self.crawled = {r["url"]: r for r in self.store.values() if r["status"] == "ok" and r["url"] not in wrong_sites}
        self.next_pass = {"browser": [], "browser_hard": []}
        self.saved, self.total, self.unreachable_in_a_row = 0, 0, 0

    def needs_crawl(self, account_id, url):
        """Whether to crawl this account now. Yes when:
          - it has never been crawled, or it is in RECRAWL_IDS
          - its last crawl isn't final: it was refused or didn't answer, with tries left (crawled again until it has
            had MAX_ATTEMPTS tries; after that the record is final and Phase 2 moves on)
          - Phase 2 found the stored website isn't the company's, and the CRM now has a different web address
        Otherwise (finished, or a wrong website still in the CRM) it is skipped."""
        rec = self.store.get(account_id)
        if rec is None or account_id in self.recrawl or not rec["final"]:
            return True
        if rec["status"] == "wrong_site":
            return url != rec["url"]
        return rec["status"] in TRY_AGAIN and rec["attempts"] < MAX_ATTEMPTS

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
        if record["status"] == "ok":
            self.crawled[record["url"]] = record
        self.unreachable_in_a_row = self.unreachable_in_a_row + 1 if record["status"] == "unreachable" else 0
        reason = f" ({record['reason']})" if record.get("reason") else ""
        print(f"[{self.saved}/{self.total}] {record['url'] or '-'}: {record['status']}{reason}, "
              f"{len(record['pages'])} pages, {record['seconds']}s")

    def save_site(self, site):
        """Save a finished website for every account that has it (accounts sharing a website are crawled once).
        The try count goes up by one on each run that crawls the account again; it starts again at 1 when the
        crawl was asked for (RECRAWL_IDS) or the CRM has a new web address after a wrong-website finding."""
        for account in site["accounts"]:
            row = account["row"]
            previous = self.store.get(row["account_id"])
            first_try = previous is None or row["account_id"] in self.recrawl or previous["status"] == "wrong_site"
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


def run(input_xlsx, store_path, limit=None, recrawl_ids=()):
    """Crawl every account in input_xlsx that needs it (CrawlRun.needs_crawl). limit: at most this many accounts.
    recrawl_ids: account_ids to crawl again even though they are stored."""
    JOBS.mkdir(exist_ok=True)
    recrawl = {i.lower() for i in recrawl_ids}
    crawl_run = CrawlRun(store_path, recrawl)
    if any(JOBS.glob("part_*.jsonl")):  # the last run was cut off: keep what its workers had finished
        crawl_run.collect({})
        clear_jobs()

    accounts = load_accounts(input_xlsx)
    todo = [(excel_row, row) for excel_row, row in accounts.iterrows()
            if crawl_run.needs_crawl(row["account_id"], row["url"])]
    print(f"{len(accounts)} accounts | {len(accounts) - len(todo)} already stored | {len(todo)} to crawl"
          + (f" | {min(limit, len(todo))} this run" if limit else ""))
    todo = todo[:limit] if limit else todo
    crawl_run.total = len(todo)

    to_crawl = {}  # website -> the accounts that have it
    for excel_row, row in todo:
        url = row["url"]
        if not url:
            crawl_run.save(store_record(excel_row, row, "no_website"))
        elif is_social_page(url):
            crawl_run.save(store_record(excel_row, row, "social_media_page_only"))
        elif url in crawl_run.crawled and row["account_id"] not in recrawl:  # crawled already for another account
            source = crawl_run.crawled[url]
            crawl_run.save(store_record(excel_row, row, "ok", source["pages"], reason=source.get("reason")))
        else:
            to_crawl.setdefault(url, []).append({"excel_row": int(excel_row), "row": row.to_dict()})

    start = time.perf_counter()
    try:
        sites = [{"url": url, "accounts": accounts_with_it} for url, accounts_with_it in to_crawl.items()]
        for mode, name, workers in PASSES:
            if mode != "http":  # passes 2 and 3 get the sites the pass before handed on
                sites, crawl_run.next_pass[mode] = crawl_run.next_pass[mode], []
            crawl_run.run_pass(mode, name, workers, sites)
    finally:
        print(f"\n{crawl_run.saved} of {len(todo)} saved in {(time.perf_counter() - start) / 60:.1f} min. "
              "Re-run to continue if it stopped.")


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
