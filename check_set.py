"""The check set: a fixed list of accounts we have already worked through, each with the answer we agreed on, run
again after any change to the questions or the decision rules to see that nothing broke.

The list is data/check_set.xlsx (kept out of git: it names real accounts). One row per account:
  Account, Group, Expected, Main business, Tier, Asks, Why, Store, Website, account_id
  Expected        an industry ("Septic", "Other", ...), "website issue" or "held back"
  Main business   "Yes" / "No", or blank when it doesn't matter
  Tier            Clear Case    clear-cut accounts: any miss is a regression
                  Decided Case  edge cases we have ruled on: most should pass
                  Unclear Case  open questions and toss-ups: reported, never graded
  Asks            how many times to ask (3 for known toss-ups, so noise isn't mistaken for a change)
  Store           the crawl store the account's pages are read from (no new crawling: only the rules change)

run() asks the model once per ask, grades every account and writes data/check_runs/<date_time>/check_report.xlsx
with what passed, what failed, and what changed since the previous check run.
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import classify
import decide
import questions
import report
from accounts import load_contacts
from results import PARTIAL_BOT_CHECK_UNSURE, load_answers
from crawl import load_store

DATA = Path(__file__).parent / "data"
CHECK_SET = DATA / "check_set.xlsx"
RUNS = DATA / "check_runs"
WEBSITE_ISSUE, HELD_BACK = "website issue", "held back"
CLEAR, DECIDED, UNCLEAR = "Clear Case", "Decided Case", "Unclear Case"  # the tiers


def records(check_set):
    """The stored crawl of every account in the set. A website-check mark from an earlier run is cleared, so the
    check is judged again by today's rules."""
    out = []
    for store_name, rows in check_set.groupby("Store"):
        store = load_store(DATA / store_name)
        for _, row in rows.iterrows():
            rec = store.get(row["account_id"]) or store.get(row["account_id"].lower())
            if rec is None:
                raise KeyError(f"{row['Account']} is not in {store_name}")
            if rec["status"] == "wrong_site":
                rec = {**rec, "status": "ok", "site_check": None}
            out.append(rec)
    return out


def contacts_file(check_set, folder):
    """An input file with each account's CRM phone, email and DBA (taken from its own set's input file when there is
    one), so CRM details can confirm a website as they do in a normal run."""
    found = {}
    for store_name in check_set["Store"].unique():
        source = DATA / (store_name.removeprefix("crawls_").removesuffix(".jsonl") + ".xlsx")
        if source.exists():
            found.update(load_contacts(source))
    rows = [{"account_id": i, "phone_number": found.get(i.lower(), {}).get("phone", ""),
             "email_address": found.get(i.lower(), {}).get("email", ""),
             "doing_business_as": found.get(i.lower(), {}).get("dba", "")} for i in check_set["account_id"]]
    path = folder / "input.xlsx"
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


def outcome(row):
    """One answer line in the words the check set uses: an industry (with main business), a website issue, held
    back, or failed."""
    if row["status"] == "wrong_site":
        return WEBSITE_ISSUE, ""
    if row["status"] == PARTIAL_BOT_CHECK_UNSURE:
        return HELD_BACK, ""
    if row["status"] != "ok":
        return "failed", ""
    return decide.LABELS[row["segment"]], decide.main_yes(row["main_business"]) or ""


def grade(check_set, answers):
    """One row per account: what it got on each ask, and whether that matches what we agreed."""
    got = {}
    for _, row in report.current_decision(answers[answers["status"] == "ok"]).iterrows():
        got.setdefault(row["account_id"].lower(), []).append(outcome(row))
    for _, row in answers[answers["status"] != "ok"].iterrows():
        got.setdefault(row["account_id"].lower(), []).append(outcome(row))
    rows = []
    for _, item in check_set.iterrows():
        results = got.get(item["account_id"].lower(), [])
        main = item["Main business"] if isinstance(item["Main business"], str) else ""
        ok = [industry == item["Expected"] and (not main or got_main == main) for industry, got_main in results]
        passed = bool(results) and all(ok)
        rows.append({"Account": item["Account"], "Group": item["Group"], "Tier": item["Tier"],
                     "Expected": item["Expected"] + (f", main business {main}" if main else ""),
                     "Got": "; ".join(f"{i}" + (f" (main {m})" if m else "") for i, m in results) or "no answer",
                     "Result": ("pass" if passed else "FAIL") if item["Tier"] != UNCLEAR else
                               ("as expected" if passed else "differs"),
                     "Why": item["Why"], "account_id": item["account_id"]})
    return pd.DataFrame(rows)


def summary(graded):
    graded = graded.assign(passed=graded["Result"].isin(["pass", "as expected"]))
    table = graded.groupby("Tier")["passed"].agg(accounts="size", passed="sum")
    table["share"] = (table["passed"] / table["accounts"]).map("{:.0%}".format)
    return table.reindex([CLEAR, DECIDED, UNCLEAR]).dropna()


def previous_results(before):
    """The graded table of the latest earlier check run, or None."""
    earlier = sorted(p for p in RUNS.glob("*/results.csv") if p.parent.name < before)
    return pd.read_csv(earlier[-1]) if earlier else None


def run(check_set_path=CHECK_SET):
    """Ask, grade, compare with the previous check run, and write the report. Returns the graded table."""
    check_set = pd.read_excel(check_set_path, dtype={"Main business": str})
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    folder = RUNS / stamp
    folder.mkdir(parents=True, exist_ok=True)
    recs, inp = records(check_set), contacts_file(check_set, folder)
    asks = dict(zip(check_set["account_id"].str.lower(), check_set["Asks"]))
    print(f"check set: {len(check_set)} accounts, {int(check_set['Asks'].sum())} calls, questions version "
          f"{questions.QUESTIONS_VERSION}")
    for k in range(int(check_set["Asks"].max())):
        batch = [{**r, "excel_row": n + 2} for n, r in enumerate(recs) if asks[r["account_id"].lower()] > k]
        store = folder / f"crawls_ask{k + 1}.jsonl"
        store.write_text("".join(json.dumps(r) + "\n" for r in batch), encoding="utf-8")
        classify.run(store, inp, folder / f"answers_ask{k + 1}.csv", folder / f"evidence_ask{k + 1}.jsonl")
    answers = pd.concat([load_answers(p) for p in sorted(folder.glob("answers_ask*.csv"))], ignore_index=True)
    graded = grade(check_set, answers)
    graded.to_csv(folder / "results.csv", index=False)
    before = previous_results(stamp)
    if before is not None:
        last = before.set_index("account_id")["Got"]
        graded["Last run"] = graded["account_id"].map(last).fillna("")
        graded["Changed"] = (graded["Last run"] != "") & (graded["Last run"] != graded["Got"])
    with pd.ExcelWriter(folder / "check_report.xlsx") as xl:
        summary(graded).to_excel(xl, sheet_name="Summary")
        graded.sort_values(["Tier", "Result", "Group"]).to_excel(xl, sheet_name="Results", index=False)
    print(summary(graded).to_string())
    misses = graded[graded["Result"].isin(["FAIL", "differs"])]
    if not misses.empty:
        print("\n" + misses[["Tier", "Account", "Expected", "Got"]].to_string(index=False))
    print(f"\nreport: {folder / 'check_report.xlsx'}")
    return graded


if __name__ == "__main__":
    run()
