"""Compare models (Decision-1 and Jev) on the same accounts, with identical input and the same decisions.

  run()     every account with a usable website goes to each model once; one CSV line per call
  report()  an Excel comparison: side by side per account, agreement, each model against the input file's label

Both models read exactly what Phase 2 sends (classify.build_state) and answer the same questions; their scores go
through the same thresholds (decide.py), so the model is the only difference. This never writes to the crawl store
(website-check marks are Phase 2's job).
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
from openpyxl import Workbook

import decide
import model_api
import classify
import report as phase2_report
import results
import report_guide
from accounts import load_accounts, load_contacts
from results import FIELDS, answer_row
from crawl import load_store

FIELDS = ["model", *FIELDS]


def answer(rec, state, crm, model, future):
    """One answers line for one model's call."""
    row = {"model": model, "account_id": rec["account_id"], "excel_row": rec["excel_row"],
           "name": rec["company"].get("name", ""), "url": rec["url"],
           "label": rec.get("reference", {}).get("industry_types", ""), "crm_evidence": crm,
           "evidence": ", ".join(results.segment_evidence(state)), "pages_sent": len(state["website"]["pages"]),
           "words_sent": sum(len(p["text"].split()) for p in state["website"]["pages"]),
           "run_at": datetime.now().isoformat(timespec="seconds"), "error_stage": "", "error": ""}
    try:
        answers, tokens, seconds = future.result()
        row.update(answer_row(answers), input_tokens=tokens, seconds=round(seconds, 1))
    except Exception as err:  # noqa: BLE001 (saved as failed; retried next run)
        return {**row, "status": "failed", "error_stage": results.CALL, "error": results.call_error(err)}
    return {**row, "status": "wrong_site" if decide.wrong_site(row["site_match"], crm) else "ok"}


def append(path, row):
    new_file = not path.exists() or not path.stat().st_size
    pd.DataFrame([row]).reindex(columns=FIELDS).to_csv(path, mode="a", header=new_file, index=False)


def run(store_path, input_xlsx, answers_csv, models=("decision1", "jev"), workers=4, limit=None):
    """Call each model for every account with a usable website that it hasn't answered yet. Safe to re-run."""
    store, contacts = load_store(store_path), load_contacts(input_xlsx)
    done = set()
    if answers_csv.exists():
        old = pd.read_csv(answers_csv, dtype={"account_id": str})
        done = set(zip(old.loc[old.status != "failed", "model"], old.loc[old.status != "failed", "account_id"]))
    accounts = []
    for rec in sorted(store.values(), key=lambda r: r["excel_row"]):
        contact = contacts.get(rec["account_id"], {})
        state = classify.build_state(rec, contact.get("dba")) if rec["final"] else None
        crm = classify.crm_evidence(rec, contact) if state else ""
        if state and rec["status"] == "ok":
            accounts.append((rec, state, crm))
    accounts = accounts[:limit] if limit else accounts
    todo = [(rec, state, crm, m) for rec, state, crm in accounts for m in models if (m, rec["account_id"]) not in done]
    print(f"{len(accounts)} accounts with a usable website | {len(todo)} calls to make ({', '.join(models)})")
    for m in models:
        model_api.api_key(m)  # fails here, before any call, if a key isn't set

    start, n = time.perf_counter(), 0
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(model_api.ask, state, m): (rec, state, crm, m) for rec, state, crm, m in todo}
        for future in as_completed(futures):
            rec, state, crm, m = futures[future]
            row = answer(rec, state, crm, m, future)
            append(answers_csv, row)
            n += 1
            said = row["error"] or f"{decide.LABELS[row['segment']]} {row['probability']:.0%}"
            print(f"[{n}/{len(todo)}] {model_api.MODELS[m]['name']:10} {row['name'][:36]:36} | {said}")
    print(f"\n{n} calls in {(time.perf_counter() - start) / 60:.1f} min. Re-run to retry failures.")


def bars_for(model, thresholds):
    """The model's own Other bar and main-business safety net, if set
    (e.g. {"jev": {"other_threshold": 0.85}})."""
    return {"other_threshold": decide.OTHER_THRESHOLD,
            "safety_net_threshold": decide.SAFETY_NET_THRESHOLD, **(thresholds or {}).get(model, {})}


def side_by_side(answers_csv, label_name="", models=("decision1", "jev"), thresholds=None):
    """One row per account, grouped so related columns sit together: the industries (label, each model, agreement,
    each model vs the label), then the probabilities (coloured by how sure), then main business, then the rationales.
    Each model's scores go through decide.redecide with its own bars."""
    answers = pd.read_csv(answers_csv, dtype={"account_id": str})
    answers = answers[answers.status == "ok"].drop_duplicates(["model", "account_id"], keep="last")
    accounts = answers.drop_duplicates("account_id").set_index("account_id")
    names = [model_api.MODELS[m]["name"] for m in models]
    label = f"{label_name} industry"

    # Each model's decisions, with its own bars
    decisions, other_bar = {}, {}
    for m, name in zip(models, names):
        bars = bars_for(m, thresholds)
        decisions[name] = phase2_report.current_decision(answers[answers.model == m], **bars).set_index("account_id")
        other_bar[name] = bars["other_threshold"]

    wide = pd.DataFrame({"Account": accounts["name"], "Website": accounts["url"],
                         "CRM": [report_guide.CRM_URL.format(account_id=i) for i in accounts.index]})
    if label_name:
        wide[label] = accounts["label"]
    # 1. The industries
    for name in names:
        wide[name] = decisions[name]["segment"].map(decide.LABELS)
    answered_by_both = wide[names].notna().all(axis=1)
    same = wide[names].nunique(axis=1) == 1
    wide["Models agree"] = same.map({True: "Yes", False: "No"}).where(answered_by_both, "")
    if label_name:
        for name in names:
            matches = wide[name].str.lower() == wide[label].str.lower()
            agreement = matches.map({True: "Match", False: "Mismatch"})
            wide[f"{name} vs {label_name}"] = agreement.where(wide[name].notna(), "")
    # 2. How sure, 3. main business, 4. why
    for name in names:
        wide[f"{name} probability"] = decisions[name]["probability"]
    for name in names:
        wide[f"{name} main business"] = decisions[name]["main_business"].map(decide.main_yes)
    for name in names:
        wide[f"{name} rationale"] = decisions[name].apply(decide.rationale, axis=1,
                                                          other_threshold=other_bar[name])
    wide["excel_row"] = accounts["excel_row"]
    return wide.reset_index().sort_values("excel_row").drop(columns="excel_row")


def not_classified(answers_csv, models, store_path, input_xlsx, label_name=""):
    """Every account in the input file that a model didn't classify, with the stage it stopped at and why. A crawl
    problem stops it for both models; a website check or a failed call can stop one model and not the other."""
    accounts = load_accounts(input_xlsx)
    store = load_store(store_path)
    answers = pd.read_csv(answers_csv, dtype={"account_id": str}).drop_duplicates(["model", "account_id"], keep="last")
    latest = answers.set_index(["model", "account_id"])
    names = {m: model_api.MODELS[m]["name"] for m in models}
    rows = []
    for _, account in accounts.iterrows():
        rec, aid = store.get(account["account_id"]), account["account_id"]
        if rec is None:
            stops = {"Both": (results.CRAWL, "not crawled yet (run the crawl)")}
        elif rec["status"] not in ("ok", "wrong_site"):  # the crawl found nothing to send
            stops = {"Both": results.not_sent_reason(rec, True, "") or (results.CRAWL, rec["status"])}
        else:
            stops = {}
            for m in models:
                if (m, aid) not in latest.index:
                    stops[names[m]] = (results.CONTENT, "not sent: no usable website text, or not run yet")
                    continue
                row = latest.loc[(m, aid)]
                if row["status"] == "wrong_site":
                    stops[names[m]] = (results.SITE, f"website issue (site check {row['site_match']:.2f})")
                elif row["status"] != "ok":
                    stops[names[m]] = (results.CALL,
                                       results.short_error(row.get("error")) or "the call failed")
            same = {(stage, phase2_report.problem_kind(problem)) for stage, problem in stops.values()}
            if len(stops) == len(models) and len(same) == 1:  # every model stopped at the same place, same reason
                stops = {"Both": next(iter(stops.values()))}
        for model, (stage, problem) in stops.items():
            rows.append({"Account": account["name"], "Website": account["url"] or "",
                         **({f"{label_name} industry": account.get("industry_types", "")} if label_name else {}),
                         "Model": model, "Stopped at": stage, "Problem": problem,
                         "CRM": report_guide.CRM_URL.format(account_id=aid), "account_id": aid})
    return pd.DataFrame(rows)


def other_bar_table(answers_csv, model, thresholds):
    """For one model: how many accounts it would call Other at each Other bar (its main-business safety net as set),
    to see what moving the bar would do. Returns (table, a sentence about the safety net)."""
    answers = pd.read_csv(answers_csv, dtype={"account_id": str})
    answers = answers[(answers.status == "ok") & (answers.model == model)].drop_duplicates("account_id", keep="last")
    bars = bars_for(model, thresholds)
    rows = []
    for other_bar in (0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95):
        decided = phase2_report.current_decision(answers, other_threshold=other_bar,
                                                 safety_net_threshold=bars["safety_net_threshold"])
        in_use = "<- in use" if abs(other_bar - bars["other_threshold"]) < 1e-9 else ""
        rows.append({"Other bar": f"{other_bar:.2f}",
                     "Accounts called Other": int((decided["segment"] == "other").sum()),
                     "": in_use})
    # The safety net only matters if some Other has a high main-business score
    model_others = phase2_report.current_decision(answers, **bars)
    model_others = model_others[model_others["segment"] == "other"]
    main_columns = [c for c in answers.columns if c.startswith("main_") and c != "main_business"]
    highest = model_others[main_columns].max(axis=1).max() if len(model_others) else 0
    net_note = (f"The main-business safety net is {bars['safety_net_threshold']:.2f}. The highest main-business score "
                f"among this model's Others is {highest:.2f}, so the net "
                + ("changes nothing here." if highest < 0.30 else "matters for some accounts: see their rationales."))
    return pd.DataFrame(rows).set_index("Other bar"), net_note


def guide(label_name, models, thresholds):
    """The Guide sheet: what each column means, the colours, and each model's thresholds."""
    names = [model_api.MODELS[m]["name"] for m in models]
    sections = {"The columns (All accounts, Disagreements)": [
        (report_guide.ACCOUNT_LINK, "the CRM account's name; click it to open the website both models read "
                                     "(identical input)"),
        ("CRM", "click 'link' to go to the account in the CRM"),
        *([(f"{label_name} industry", "the industry the input file gives; never used to decide")]
          if label_name else []),
        (" / ".join(names), "each model's industry after our thresholds (its own bars, below)"),
        ("Models agree", "Yes when both models give the same industry"),
        *([(f"<model> vs {label_name}", f"Match when that model gives the {label_name} industry")]
          if label_name else []),
        ("<model> probability", "the model's probability for its industry, coloured by how sure: green High, "
                               "yellow Medium, red Low (Thresholds below)"),
        ("<model> main business", "Yes: that segment's work is the main business; No: done alongside another; "
                                  "blank for Other"),
        ("<model> rationale", "why: the rule that decided it, main business, pages naming the work, website check"),
    ], "Not classified sheet": [
        ("Model", "which model stopped: Both (a crawl problem stops every model) or one model (its website check "
                  "said the site isn't the company's, or its call failed)"),
        ("Stopped at, Problem", "the stage (1 crawl, 2 website text, 3 model call, 4 website check) and why"),
    ], "Colours": [
        ("Headers", "blue: the answers; orange: how sure; green: main business; grey: explanations"),
        ("Cells", "probability: green High, yellow Medium, red Low; Match and agree green, Mismatch and disagree red"),
    ], "Summary: the Other bar tables": [
        ("What they show", "for each model, how many accounts it would call Other if its Other bar were 0.60, 0.65, "
         "... 0.95 ('<- in use' marks the bar set now). A higher bar means fewer Others: accounts the model is "
         "less sure about get their likeliest segment instead. The sentence in the title says whether the "
         "main-business safety net changes anything"),
        ("Changing a bar", "set it in THRESHOLDS in compare_models.ipynb and re-run the report cell: no new calls"),
    ]}
    for m, name in zip(models, names):
        sections[f"{name}: thresholds in use"] = report_guide.thresholds_guide(bars_for(m, thresholds))
    return sections


def report(answers_csv, report_xlsx, label_name="", models=("decision1", "jev"), thresholds=None, store_path=None,
           input_xlsx=None):
    """Excel comparison: Guide, Summary, Disagreements (the accounts to look at), All accounts, Not classified. Also
    a CSV. thresholds: a model's own bars, e.g. {"jev": {"other_threshold": 0.70}}; others use decide.py's.
    store_path and input_xlsx (the crawl store and the input file) are needed for the Not classified sheet."""
    table = side_by_side(answers_csv, label_name, models, thresholds)
    names = [model_api.MODELS[m]["name"] for m in models]
    both = table[table["Models agree"] != ""]
    summary = {"Both models": pd.DataFrame({"accounts": [len(both), (both["Models agree"] == "Yes").sum()]},
                                           index=["Answered by both", "Same industry"])}
    if len(names) == 2:
        summary[f"{names[0]} (rows) vs {names[1]} (columns)"] = pd.crosstab(both[names[0]], both[names[1]],
                                                                         margins=True, margins_name="Total")
    # One small table per question, with a column per model
    industries, sure, against_label = {}, {}, {}
    for name in names:
        industries[name] = table[name].value_counts()
        bands = table[f"{name} probability"].dropna().map(decide.how_sure)
        sure[name] = bands.value_counts().reindex(["High", "Medium", "Low"])
        if label_name:
            against_label[name] = table[f"{name} vs {label_name}"].value_counts()
    summary["Industries"] = pd.DataFrame(industries).fillna(0).astype(int)
    high, medium = decide.HIGH_BAND, decide.MEDIUM_BAND
    bands = (f"High {high:.0%}+, Medium {medium:.0%}-{high:.0%}, "
             f"Low under {medium:.0%}")
    summary[f"How sure ({bands})"] = pd.DataFrame(sure).fillna(0).astype(int)
    if label_name:
        summary[f"Each model vs {label_name}"] = pd.DataFrame(against_label).fillna(0).astype(int)
    for m, name in zip(models, names):
        table_of_bars, net_note = other_bar_table(answers_csv, m, thresholds)
        summary[f"{name}: how many accounts are Other at each Other bar. {net_note}"] = table_of_bars
    stopped = not_classified(answers_csv, models, store_path, input_xlsx, label_name) if store_path and input_xlsx \
        else pd.DataFrame()
    if not stopped.empty:
        summary["Not classified: where it stopped and why, by model (details on the Not classified sheet)"] = \
            phase2_report.not_classified_counts(stopped, by="Model")

    wb = Workbook()
    ws = wb.active
    ws.title = "Guide"
    phase2_report.write_guide(ws, guide(label_name, models, thresholds))
    phase2_report.write_tables(wb.create_sheet("Summary"), summary, first_width=40)
    wrap = tuple(f"{n} rationale" for n in names)
    for name, rows in (("Disagreements", both[both["Models agree"] == "No"]), ("All accounts", table)):
        rows, links = phase2_report.with_links(rows)  # Account (website-link) and CRM link, frozen
        phase2_report.write_sheet(wb.create_sheet(name), rows, wrap, links=links, frozen=2)
    if not stopped.empty:
        rows, links = phase2_report.with_links(stopped)
        phase2_report.write_sheet(wb.create_sheet("Not classified"), rows, ("Problem",), links=links, frozen=2)
    table.to_csv(report_xlsx.with_name(report_xlsx.stem + "_accounts.csv"), index=False)
    tmp = report_xlsx.with_name("~tmp_" + report_xlsx.name)
    wb.save(tmp)
    try:
        tmp.replace(report_xlsx)
        print(f"Saved {report_xlsx.name}: {len(both)} accounts answered by both, "
              f"{(both['Models agree'] == 'No').sum()} disagreements")
    except PermissionError:
        print(f"{report_xlsx.name} is open in Excel; saved as {tmp.name} instead")
