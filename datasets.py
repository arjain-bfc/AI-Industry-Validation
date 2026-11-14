"""The account sets the notebooks run on: how each is picked, and its files. Pick one by name (SET = "crm_pilot").

How a set is picked (make):
  - from the data warehouse (data_warehouse.py, queries/): ZoomInfo accounts with no LCW opportunity, or CRM accounts.
    The latest snapshot of the query is used; refresh=True reads the warehouse again first
  - a number per label: the five segments, plus Other for the CRM (ZoomInfo's Other is everything outside our
    segments, so it isn't sampled). Within a label, by the set's PICK rule:
      "newest"  the most recently created accounts (crm_created_on)
      "recent"  a random pick among accounts created in the last RECENT_MONTHS months (newer accounts crawl better,
                and a random pick avoids one bulk import filling a label)
      "random"  a random pick among all of them
  - only accounts with a website: not empty, and not a social media, directory or marketplace listing (a company's
    own Facebook or Instagram page counts)
  - each company once: a second CRM record of the same company (same website and name) is never picked
  - never an account already in another set or already crawled, so no account is tested twice
  - the aim is a number of USABLE accounts per label (crawled fine). Some sites turn out dead, parked or unreachable,
    so a set starts with PAD extra, and top_up() adds more for any label still short after the crawl.

Every file of a set is named after its input file:
  data/crm_100each.xlsx  ->  crawls_crm_100each.jsonl, answers_crm_100each.csv, evidence_crm_100each.jsonl,
                             report_crm_100each.xlsx, crawl_summary_crm_100each.xlsx

A new set: add a line to SETS with a new input name, then run make(name) once (it never overwrites a set). After
its crawl, run top_up(name) and crawl again if any label came out short.
"""
import math
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import decide
import data_warehouse
from accounts import is_listing_link, load_accounts, same_company_key
from crawl import load_store


DATA = Path(__file__).parent / "data"


SEGMENTS = [label for key, label in decide.LABELS.items() if key != "other"]  # as the CRM names them


SOURCES = {"ZoomInfo": "zoominfo", "CRM": "crm"}                             # the query each label comes from


LABELS = {"ZoomInfo": SEGMENTS, "CRM": SEGMENTS + ["Other"]}                 # which labels are sampled


PAD = 1.25          # pick 25% more than the usable accounts wanted: about 10-15% of sites turn out dead or unreachable


RECENT_MONTHS = 1   # the "recent" rule's window: accounts created in the last month


SETS = {  # name: (input file in data/, label source, usable accounts wanted per label, PICK rule)
    "zoominfo_pilot": ("zoominfo_30each.xlsx", "ZoomInfo", 30, "recent"),  # pilots: the full pipeline on fresh
    "crm_pilot": ("crm_30each.xlsx", "CRM", 30, "recent"),                 #   accounts, before the big runs
    "zoominfo_3": ("zoominfo_100each_3.xlsx", "ZoomInfo", 100, "recent"),  # after the pilots: make() then skips
    "crm_100": ("crm_100each.xlsx", "CRM", 100, "recent"),                 #   the pilots' accounts
    "zoominfo_2": ("zoominfo_100each_2.xlsx", "ZoomInfo", 100, "newest"),  # first 118 per segment picked at random
                                                                           #   (2026-11-09); top-ups the newest
    "crm_20": ("crm_20each.xlsx", "CRM", 20, "newest"),
}


OTHER_INPUTS = ["compare_20each.xlsx", "zoominfo_500.xlsx", "zoominfo_100each.xlsx"]  # earlier test sets, never reused


def files(name):
    """Every file of one set: .input, .store, .summary, .answers, .evidence, .report, and .label."""
    input_file, label, _, _ = SETS[name]
    stem = Path(input_file).stem
    return SimpleNamespace(input=DATA / input_file, label=label,
                           store=DATA / f"crawls_{stem}.jsonl", summary=DATA / f"crawl_summary_{stem}.xlsx",
                           answers=DATA / f"answers_{stem}.csv", evidence=DATA / f"evidence_{stem}.jsonl",
                           report=DATA / f"report_{stem}.xlsx")


def used_accounts():
    """Files whose accounts must never be picked again: every crawl store and every set's input file."""
    return [*DATA.glob("crawls_*.jsonl"),
            *(DATA / f for f, *_ in SETS.values() if (DATA / f).exists()),
            *(DATA / f for f in OTHER_INPUTS if (DATA / f).exists())]


def make(name, refresh=False):
    """Write a set's input file by its rule (see the top of this file). Refuses if the file is already there.
    refresh=True reads the warehouse again first; otherwise its latest snapshot is used."""
    input_file, label, wanted, pick = SETS[name]
    out = DATA / input_file
    if out.exists():
        raise FileExistsError(f"{input_file} already exists: give a new set a new name in SETS")
    pool = data_warehouse.accounts(SOURCES[label], refresh)
    make_sample(pool, math.ceil(wanted * PAD), out, exclude=used_accounts(), per_label=True,
                      labels=LABELS[label], pick=pick, recent_months=RECENT_MONTHS)


def top_up(name, write=True, refresh=False):
    """After a crawl: for each label with fewer usable accounts than wanted, add more accounts by the set's rule (the
    shortfall plus PAD) to the set's input file, so a second crawl brings it up to about the number wanted. Accounts
    whose crawl isn't finished yet (to be retried) count as usable for now. write=False only shows what it would add.
    Returns {label: accounts added}."""
    f = files(name)
    _, label, wanted, pick = SETS[name]
    store = load_store(f.store)
    current = pd.read_excel(f.input, dtype=str)
    usable = {}
    for rec in store.values():
        if rec["status"] == "ok" or not rec["final"]:
            usable[rec["reference"]["industry_types"]] = usable.get(rec["reference"]["industry_types"], 0) + 1
    short = {each: wanted - usable.get(each, 0) for each in LABELS[label] if usable.get(each, 0) < wanted}
    added = {each: math.ceil(missing * PAD) for each, missing in short.items()}
    if added and write:
        pool = data_warehouse.accounts(SOURCES[label], refresh)
        extra = make_sample(pool, added, exclude=used_accounts(), pick=pick, recent_months=RECENT_MONTHS)
        pd.concat([current, extra[current.columns]], ignore_index=True).to_excel(f.input, index=False)
    print(f"{'Added' if write else 'Would add'}: {added or 'nothing, every label has enough'}")
    return added


# --- Picking the accounts for a set -----------------------------------------------------------------------------------
def make_sample(pool, n, out_xlsx=None, exclude=(), per_label=False, labels=None, seed=42, pick="random",
                recent_months=12):
    """Pick accounts that have a real website from pool (a table from data_warehouse.accounts, or an Excel file), write
    them to out_xlsx (same columns) if given, and return them.
      n          how many: in total, or per label with per_label; or {label: how many} for different numbers per label
      exclude    crawl stores (.jsonl) or input files (.xlsx) whose accounts must not be picked, so sets never overlap
                 (nor a second record of the same company, see same_company_key)
      per_label  True: n accounts for each industry_types label (all of a label that has fewer); False: n in total
      labels     only these industry_types labels, e.g. the five segments
      pick       "random"; "newest": the most recently created (crm_created_on); "recent": random among those
                 created in the last recent_months months (all of a label's newest when it has too few)"""
    if isinstance(n, dict):
        per_label, labels = True, list(n)
    raw = (pool if isinstance(pool, pd.DataFrame) else pd.read_excel(pool, dtype=str)).reset_index(drop=True)
    accounts = load_accounts(raw)
    used = set()
    for path in map(Path, exclude):
        used |= set(load_store(path)) if path.suffix == ".jsonl" else set(load_accounts(path)["account_id"])
    dba = accounts.get("doing_business_as", pd.Series("", accounts.index))
    accounts = accounts.assign(company_key=[same_company_key(u, name, d)
                                            for u, name, d in zip(accounts["url"], accounts["name"], dba)])
    used_keys = set(accounts.loc[accounts["account_id"].isin(used), "company_key"])
    candidates = accounts[accounts["url"].notna() & ~accounts["url"].fillna("").map(is_listing_link)
                          & ~accounts["account_id"].isin(used) & ~accounts["company_key"].isin(used_keys)]
    candidates = candidates.drop_duplicates("company_key")  # a company entered twice in the CRM is picked once
    if labels:
        candidates = candidates[candidates["industry_types"].isin(labels)]
    groups = list(candidates.groupby("industry_types")) if per_label else [("", candidates)]
    how_many = (lambda label: n[label]) if isinstance(n, dict) else (lambda label: n)
    created = pd.to_datetime(candidates["crm_created_on"], errors="coerce")  # as dates: text sorts "1/9" after "1/10"
    cutoff = pd.Timestamp.now() - pd.DateOffset(months=recent_months)

    def take(group, k):
        newest_first = group.loc[created[group.index].sort_values(ascending=False).index]
        if pick == "newest":
            return newest_first.head(k)
        if pick == "recent":
            recent = group[created[group.index] >= cutoff]
            return recent.sample(k, random_state=seed) if len(recent) >= k else newest_first.head(k)
        return group.sample(min(k, len(group)), random_state=seed)

    picked = pd.concat([take(g, how_many(label)) for label, g in groups])
    rows = raw.loc[picked.sort_index().index - 2]
    if out_xlsx:
        rows.to_excel(out_xlsx, index=False)
    written = f" -> {Path(out_xlsx).name}" if out_xlsx else ""
    print(f"{len(picked)} of {len(candidates)} fresh accounts with a website{written}")
    print(picked["industry_types"].value_counts().to_string())
    return rows
