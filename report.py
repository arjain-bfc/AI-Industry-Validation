"""Phase 2's Excel report, rebuilt from the answers file, the evidence log and the crawl store (any time, as often as
you like). Also writes the Accounts sheet as a CSV next to the report.

Sheets:
  How it decides   what the model answers (7 questions, 12 numbers), which numbers decide each result, worked
                   examples, then the process step by step with the thresholds in use
  Guide            what every column means, the colours, and the thresholds in use
  Summary          accounts per segment and main business; agreement with the input file's label; stage counts
  Review           segments the model itself found unlikely: under 0.50 when they differ from the input file's
                   label (ZoomInfo or CRM), under 0.30 when they match it. The ones to check. Verdicts and
                   notes are kept when the report is rebuilt
  Label differences  every other difference from the label: worth a skim, above all the ones we call Other.
                   Verdicts and notes kept too. Other accounts that match the label need no check
  Non-core         accounts that do a segment's work alongside a different main business (main business No)
  Not classified   accounts that stopped before a decision: the stage (crawl, website text, model call, website
                   check) and the problem, e.g. a dead site or a wrong CRM website
  Accounts         every account in the input file (Output 1): the result, how sure, main business, match with the
                   label and a one-line rationale; or, if it wasn't classified, the stage it stopped at and why (the
                   evidence log, Output 2, has the full detail)
"""
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import decide
from accounts import load_accounts
from crawl import load_store
from results import (CALL, DECISION, PARTIAL_BOT_CHECK_UNSURE, SITE, load_answers, not_sent_reason,
                     short_error)
from report_guide import (ACCOUNT_LINK, AI_INDUSTRY, ai_probability_for, CRM_URL, how_it_decides, KEY, NOTES,
                          OLD_VERDICT, report_guide, VERDICT, what_the_model_answers)


# --- Output 1: one row per classified account --------------------------------------------------------------------
def current_decision(answers, **bars):
    """The saved answers with segment, probability, rule and main business worked out again under today's thresholds
    (decide.redecide), so answers saved under earlier thresholds read the same as new ones. bars: a model's own
    other_threshold / safety_net_threshold, used by the model comparison."""
    answers = answers.copy()
    decided = []
    for _, row in answers.iterrows():
        segment, probability, rule = decide.redecide(row, **bars)
        main = None if segment == "other" else row[f"main_{segment}"]  # the chosen segment's score; none for Other
        decided.append((segment, probability, rule, main))
    columns = ["segment", "probability", "how", "main_business"]
    answers[columns] = pd.DataFrame(decided, columns=columns, index=answers.index)
    return answers


def accounts_table(answers, label_name):
    """Output 1: one readable row per classified account (its latest answer)."""
    latest = answers.drop_duplicates("account_id", keep="last")  # a later "wrong site" or "held back" replaces an
    ok = latest[latest["status"] == "ok"]                          # earlier answer: only the latest one counts
    if ok.empty:
        return pd.DataFrame()
    ok = current_decision(ok)
    ours = ok["segment"].map(decide.LABELS)
    review = ok.apply(decide.review_reasons, axis=1)

    # The label from the input file (ZoomInfo or CRM industry), compared with ours
    label = ok["label"].fillna("").astype(str).str.strip()
    has_label = bool(label_name) and label.ne("").any()
    match, backing = [], []
    for label_text, our_label, (_, row) in zip(label, ours, ok.iterrows()):
        if not label_text:
            match.append("")
        else:
            match.append("Match" if label_text.lower() == our_label.lower() else "Mismatch")
        # how much the model backs the label's industry: its probability for that option
        option = KEY.get(label_text.lower())
        backing.append(row.get(f"p_{option}") if option else None)
    if has_label:  # a doubtful answer that also differs from the label: say so first
        review = [f"{label_name} says {label_text}; {why}" if why and m == "Mismatch" else why
                  for m, label_text, why in zip(match, label, review)]

    table = pd.DataFrame({"account_id": ok["account_id"], "Account": ok["name"], "Website": ok["url"]})
    if has_label:
        table[f"{label_name} industry"] = label
    table[AI_INDUSTRY] = ours
    table["Probability"] = ok["probability"]
    table["Main business"] = ok["main_business"].map(decide.main_yes)
    if has_label:
        table["Match"] = match
        table[ai_probability_for(label_name)] = backing
    table["Rationale"] = ok.apply(decide.rationale, axis=1)
    table["Doubts"] = review
    table["CRM"] = [CRM_URL.format(account_id=i) for i in ok["account_id"]]
    table["excel_row"] = ok["excel_row"]
    return table.sort_values("excel_row").drop(columns="excel_row")


# --- Output 2 (summary): the stage every account reached -------------------------------------------------------
def stage_of(rec, logged, latest):
    """(stage reached, outcome, problem) for one account. Taken from the evidence log when it has the account;
    for runs from before the evidence log, worked out from the answers file or the crawl store. A website issue is
    always described from the crawl store, so older runs read the same as new ones."""
    if rec["status"] == "wrong_site":
        return SITE, "not classified", not_sent_reason(rec, True, "")[1]
    entry = logged.get(rec["account_id"])
    if entry:
        return entry["stage_reached"], entry["outcome"], entry["problem"] or ""
    if rec["account_id"] in latest.index:  # answered, but not in an evidence log
        status = latest.loc[rec["account_id"], "status"]
        if status == "ok":
            return DECISION, "classified", ""
        if status == "wrong_site":
            return SITE, "not classified", "website issue: the site doesn't show this company"
        if status == PARTIAL_BOT_CHECK_UNSURE:
            return DECISION, "not classified", "a bot check let us read only the home page"
        error = latest.loc[rec["account_id"], "error"] if "error" in latest else ""
        return CALL, status, short_error(error)
    # never sent to the model: the crawl store says why
    usable = True if rec["status"] in ("ok", "wrong_site") else None
    stop = not_sent_reason(rec, usable, "")
    return (stop[0], "not classified", stop[1]) if stop else ("", "not classified yet", "")


def stage_log(store, answers, evidence_log, keep_order=False):
    """Every account in the crawl store: the stage it reached, its outcome and, if it stopped, the problem."""
    logged = load_store(evidence_log) if evidence_log else {}
    latest = answers.drop_duplicates("account_id", keep="last").set_index("account_id")
    rows = []
    for rec in store.values():
        stage, outcome, problem = stage_of(rec, logged, latest)
        rows.append({"account_id": rec["account_id"], "Account": rec["company"].get("name", ""),
                     "Website": rec["url"], "Stage reached": stage, "Outcome": outcome, "Problem": problem,
                     "Crawl": rec["status"] + (f" ({rec['reason']})" if rec.get("reason") else ""),
                     "Pages crawled": len(rec.get("pages") or []), "excel_row": rec["excel_row"]})
    table = pd.DataFrame(rows).sort_values(["Outcome", "excel_row"])
    return table if keep_order else table.drop(columns="excel_row")


# --- Summary -----------------------------------------------------------------------------------------------------
def problem_kind(problem):
    """The problem without its detail, so like problems count together:
    'the site no longer exists (HTTP 404)' -> 'the site no longer exists'."""
    return str(problem or "").split(" (")[0].split("; ")[0].strip() or "(not given)"


def not_classified_counts(stopped, by=None):
    """How many accounts stopped where, and why: one row per stage and kind of problem (one column per model when
    `by` names a column, as in the model comparison)."""
    stopped = stopped.assign(Problem=stopped["Problem"].map(problem_kind))
    if by:
        return pd.crosstab([stopped["Stopped at"], stopped["Problem"]], stopped[by], margins=True, margins_name="Total")
    return stopped.groupby(["Stopped at", "Problem"]).size().to_frame("accounts")


def summary_tables(table, everyone, label_name):
    """{title: table} for the Summary sheet. everyone: the Accounts sheet (every account in the input file)."""
    out = {}
    stopped = everyone[everyone["Result"] == "not classified"]
    if not table.empty:
        out["Accounts per industry, by main business"] = pd.crosstab(
            table[AI_INDUSTRY], table["Main business"].replace("", "(Other)"), margins=True, margins_name="Total")
        out["How sure"] = (table["Probability"].map(decide.how_sure).value_counts()
                             .reindex(["High", "Medium", "Low"]).fillna(0)
                             .astype(int).to_frame("accounts"))
        to_check = split_for_checking(table)
        out["Where the accounts are"] = pd.DataFrame(
            {"accounts": [len(table), *map(len, to_check.values()), len(stopped)]},
            index=["All classified (Accounts sheet)", *to_check, "Not classified"])
        col = f"{label_name} industry"
        if col in table:
            out[f"{label_name} industry (rows) vs AI predicted (columns)"] = pd.crosstab(
                table[col].replace("", "(blank)"), table[AI_INDUSTRY], margins=True, margins_name="Total")
            out[f"Same as {label_name}"] = table["Match"].replace("", "(no label)").value_counts().to_frame("accounts")
    if not stopped.empty:
        out["Not classified: where it stopped and why (details on the Not classified sheet)"] = \
            not_classified_counts(stopped)
    return out


# --- What needs checking ----------------------------------------------------------------------------------------------
def split_for_checking(table):
    """The sheets that need a look, from the Accounts table. The thresholds already settle each answer, so a person
    only checks a segment the model itself found unlikely (an Other needs 0.80, so it never is):
      Review              a segment under decide.REVIEW_THRESHOLD_DIFFERS (0.50) that differs from the label, or under
                          decide.REVIEW_THRESHOLD_MATCHES (0.30) that matches it (the model leaned Other)
      Label differences   every other difference from the label
      Non-core            main business No: the company does the segment's work alongside a different main business
    With no label to compare with (an input file without an industry), Review holds the segments under 0.50."""
    if table.empty:
        return {"Review": table, "Label differences": table, "Non-core": table}
    segment, probability = table[AI_INDUSTRY] != "Other", table["Probability"]
    if "Match" in table:
        differs = table["Match"] == "Mismatch"
        to_review = segment & ((differs & (probability < decide.REVIEW_THRESHOLD_DIFFERS))
                               | (~differs & (probability < decide.REVIEW_THRESHOLD_MATCHES)))
        review, label_differences = table[to_review], table[differs & ~to_review]
    else:
        review, label_differences = table[segment & (probability < decide.REVIEW_THRESHOLD_DIFFERS)], table.iloc[0:0]
    return {"Review": review.copy(), "Label differences": label_differences.copy(),
            "Non-core": table[table["Main business"] == "No"].copy()}


def previous_verdicts(path):
    """Verdicts and notes already typed on the Review and Label differences sheets, by account_id."""
    kept = []
    for sheet in ("Review", "Label differences"):
        try:
            old = pd.read_excel(path, sheet_name=sheet, dtype=str).rename(columns={OLD_VERDICT: VERDICT})
            kept.append(old.set_index("account_id")[[VERDICT, NOTES]].fillna(""))
        except (FileNotFoundError, ValueError, KeyError):
            pass
    return pd.concat(kept) if kept else pd.DataFrame(columns=[VERDICT, NOTES])


def keep_verdicts(to_check, table, report_xlsx):
    """Carry over the verdicts and notes people typed in the report being replaced. An account someone gave a
    verdict or a note also stays on Review when a later run no longer flags it: what a person wrote is never dropped
    because the model's answer moved."""
    verdicts = previous_verdicts(report_xlsx)
    noted = verdicts.index[(verdicts[VERDICT] != "") | (verdicts[NOTES] != "")] if not verdicts.empty else []
    listed = set(to_check["Review"]["account_id"]) | set(to_check["Label differences"]["account_id"])
    if not table.empty:
        reviewed_before = table[table["account_id"].isin(noted) & ~table["account_id"].isin(listed)]
        to_check["Review"] = pd.concat([to_check["Review"], reviewed_before])
    for name in ("Review", "Label differences"):
        part = to_check[name]
        if not part.empty:
            kept = verdicts[~verdicts.index.duplicated(keep="last")].reindex(part["account_id"]).fillna("")
            part[VERDICT], part[NOTES] = kept[VERDICT].values, kept[NOTES].values


# --- Writing the sheets: layout, colours, links and the Verdict column ------------------------------------------------
# --- Look: a few soft colours, so the eye finds the answer, how sure it is, and what to check ------------------------
HEADER_FILLS = [  # (words in the column name, header colour): which group a column belongs to
    (("confidence", "probability"), "FCE4D6"),           # how sure
    (("main business",), "E2EFDA"),                       # main business
    (("rationale", "why", "problem", "notes", "verdict"), "EDEDED"),  # explanations, review
    (("industry", "decision-1", "jev", "match", "agree", "stage", "outcome"), "DDEBF7"),  # the answers
]


BAND_FILLS = {"High": "C6EFCE", "Medium": "FFEB9C", "Low": "FFC7CE"}  # a Probability cell's colour, by how sure


VALUE_FILLS = {"Match": "C6EFCE", "Mismatch": "FFC7CE"}                # agreement with the label


AGREE_FILLS = {"Yes": "C6EFCE", "No": "FFC7CE"}                         # "Models agree" only


def header_fill(column):
    name = column.lower()
    return next((colour for words, colour in HEADER_FILLS if any(w in name for w in words)), "F2F2F2")


def with_links(part):
    """For the sheets people work through: the account name (clickable, opens its website) and a short CRM link as
    the first two columns, instead of two long web addresses. Returns (table, {column: web addresses})."""
    links = {ACCOUNT_LINK: list(part["Website"]), "CRM": list(part["CRM"])}
    rest = [c for c in part.columns if c not in ("Account", "Website", "CRM")]
    table = part[["Account"] + rest].rename(columns={"Account": ACCOUNT_LINK})
    table.insert(1, "CRM", "link")
    return table, links


def write_sheet(ws, table, wrap=(), links=None, frozen=1):
    """Coloured header by group, sensible widths, frozen header row and first `frozen` columns, filters.
    Probabilities shown as percentages and coloured by how sure (High green, Medium yellow, Low red); Match/Mismatch
    and model agreement coloured too. links: {column: web addresses, one per row} makes those cells clickable."""
    if table.empty:
        ws.append(["Nothing here yet"])
        return
    if "account_id" in table:  # the key is needed to match verdicts back, but nobody reads it: last column
        table = table[[c for c in table.columns if c != "account_id"] + ["account_id"]]
    ws.append(list(table.columns))
    for row in table.itertuples(index=False):
        ws.append(["" if pd.isna(v) else v for v in row])
    for cell, column in zip(ws[1], table.columns):
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor=header_fill(column))
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for j, column in enumerate(table.columns, 1):
        letter = get_column_letter(j)
        width = max([min(len(str(column)), 18)] + [len(str(v)) for v in table[column].head(300)])
        ws.column_dimensions[letter].width = 60 if column in wrap else min(width + 2, 40)
        fills = AGREE_FILLS if column == "Models agree" else VALUE_FILLS
        for cell in ws[letter][1:]:
            if column in wrap:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            # the result's own probability, not "AI probability for the ... industry"
            result_probability = column == "Probability" or column.endswith(" probability")
            if result_probability or column.startswith("AI probability"):
                cell.number_format = "0%"
            if result_probability and isinstance(cell.value, (int, float)):
                cell.fill = PatternFill("solid", fgColor=BAND_FILLS[decide.how_sure(cell.value)])
            elif cell.value in fills:
                cell.fill = PatternFill("solid", fgColor=fills[cell.value])
    for column, addresses in (links or {}).items():
        letter = get_column_letter(list(table.columns).index(column) + 1)
        for cell, address in zip(ws[letter][1:], addresses):
            if isinstance(address, str) and address:
                cell.hyperlink = address
                cell.font = Font(color="0563C1", underline="single")
        if column == "CRM":
            ws.column_dimensions[letter].width = 8
    ws.freeze_panes = f"{get_column_letter(frozen + 1)}2"  # header row and the first columns stay in view
    ws.auto_filter.ref = ws.dimensions


def write_tables(ws, tables, first_width=34):
    """Several small titled tables one under another (Summary sheets)."""
    r = 1
    for title, part in tables.items():
        ws.cell(r, 1, title).font = Font(bold=True, size=12)
        part = part.reset_index().rename(columns={"index": ""})
        for j, col in enumerate(part.columns, 1):
            cell = ws.cell(r + 1, j, str(col))
            cell.font, cell.fill = Font(bold=True), PatternFill("solid", fgColor="DDEBF7")
        for i, values in enumerate(part.itertuples(index=False), r + 2):
            for j, v in enumerate(values, 1):
                ws.cell(i, j, v)
        r += len(part) + 3
    ws.column_dimensions["A"].width = first_width


def write_guide(ws, sections):
    """A Guide sheet: {section title: [(name, what it means)]}."""
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 34, 110
    for title, rows in sections.items():
        ws.append([title])
        ws.cell(ws.max_row, 1).font = Font(bold=True, size=12)
        for name, meaning in rows:
            ws.append([name, meaning])
            ws.cell(ws.max_row, 1).font = Font(bold=True)
            ws.cell(ws.max_row, 2).alignment = Alignment(wrap_text=True, vertical="top")
        ws.append([])


def write_how_it_decides(ws):
    """The first sheet: what the model answers and which numbers decide what (what_the_model_answers), then
    the process step by step (how_it_decides)."""
    tables = [*what_the_model_answers().items(),
              ("How an account is decided, step by step", (["Step", "What happens"], how_it_decides()))]
    for title, (columns, rows) in tables:
        ws.append([title])
        ws.cell(ws.max_row, 1).font = Font(bold=True, size=12)
        ws.append(columns)
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
        for row in rows:
            ws.append(list(row))
            ws.cell(ws.max_row, 1).font = Font(bold=True)
            for cell in ws[ws.max_row]:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.append([])
    for column, width in zip("ABCD", (34, 40, 44, 60)):
        ws.column_dimensions[column].width = width


def add_verdict_columns(ws, part):
    """A Verdict dropdown (our industries) and a yellow Notes column, for the sheets people work through."""
    headers = [cell.value for cell in ws[1]]  # as written (write_sheet moves account_id to the end)
    col = get_column_letter(headers.index(VERDICT) + 1)
    dropdown = DataValidation(type="list", formula1='"' + ",".join(decide.LABELS.values()) + '"', allow_blank=True)
    ws.add_data_validation(dropdown)
    dropdown.add(f"{col}2:{col}{len(part) + 1}")
    for cell in ws[col][1:]:
        cell.fill = PatternFill("solid", fgColor="FFF2CC")


# --- The report -------------------------------------------------------------------------------------------------------
def every_account(table, stages, input_xlsx=None):
    """Output 1: every account in the input file, one row each. Classified accounts show their result; the others
    show the stage they stopped at and why. Accounts the crawl hasn't reached yet are listed as such."""
    results = stages.merge(table.drop(columns=["Account", "Website"]), on="account_id", how="left")
    if input_xlsx:
        accounts = load_accounts(input_xlsx)
        missing = accounts[~accounts["account_id"].isin(results["account_id"])]
        results = pd.concat([results, pd.DataFrame({
            "account_id": missing["account_id"], "Account": missing["name"], "Website": missing["url"].fillna(""),
            "Stage reached": "1 crawl", "Outcome": "not classified", "Problem": "not crawled yet (run Phase 1)",
            "excel_row": missing.index})], ignore_index=True)
        label = results["account_id"].map(accounts.set_index("account_id")["industry_types"])
        for col in [c for c in table.columns if c.endswith(" industry") and not c.startswith("AI ")]:
            results[col] = results[col].fillna(label)  # the input file's label, for accounts never answered too
    results["Result"] = results[AI_INDUSTRY].fillna("not classified")
    results["CRM"] = [CRM_URL.format(account_id=i) for i in results["account_id"]]  # every account, classified or not
    first = ["Account", "Website", *[c for c in table.columns if c.endswith(" industry")
                                      and not c.startswith("AI ")]]
    result_columns = ["Result", "Probability", "Main business", "Match",
                      *[c for c in table.columns if c.startswith("AI probability")], "Rationale", "Doubts"]
    stopped = ["Stage reached", "Problem", "Crawl", "Pages crawled", "CRM", "account_id"]  # the key last
    ordered = [c for c in first + result_columns + stopped if c in results.columns]
    results["Stage reached"] = results["Stage reached"].where(results["Outcome"] != "classified", "")
    return results.sort_values("excel_row")[ordered].rename(columns={"Stage reached": "Stopped at"})


def build(store_path, answers_csv, report_xlsx, label_name="", evidence_log=None, input_xlsx=None):
    """Write the report and the accounts CSV. label_name = what the input file's industry_types column is
    ("ZoomInfo", "CRM"); "" when there's nothing to compare with. input_xlsx: the input file, so accounts the crawl
    hasn't reached yet are listed too."""
    store = load_store(store_path)
    answers = load_answers(answers_csv)
    table = accounts_table(answers, label_name)
    stages = stage_log(store, answers, evidence_log, keep_order=True)
    everyone = every_account(table, stages, input_xlsx)
    to_check = split_for_checking(table)
    keep_verdicts(to_check, table, report_xlsx)

    wb = Workbook()
    wb.active.title = "How it decides"
    write_how_it_decides(wb.active)
    write_guide(wb.create_sheet("Guide"), report_guide(label_name))
    write_tables(wb.create_sheet("Summary"), summary_tables(table, everyone, label_name))

    for name, part in to_check.items():
        ws = wb.create_sheet(name)
        if name == "Non-core":  # a list to count, not to check: the answer, how sure, and why
            part = part.drop(columns=[c for c in part.columns if c in ("Doubts", "Main business", "Match")
                                      or c.startswith("AI probability")])
        part, links = with_links(part)
        write_sheet(ws, part, ("Rationale", "Doubts", NOTES), links=links, frozen=2)
        if VERDICT in part:
            add_verdict_columns(ws, part)
    stopped = everyone[everyone["Result"] == "not classified"]
    stopped = stopped[[c for c in stopped.columns if c in (
        "Account", "Website", f"{label_name} industry", "Stopped at", "Problem", "Crawl", "Pages crawled", "CRM",
        "account_id")]]
    stopped, links = with_links(stopped)
    write_sheet(wb.create_sheet("Not classified"), stopped, ("Problem",), links=links, frozen=2)
    write_sheet(wb.create_sheet("Accounts"), everyone, ("Rationale", "Doubts", "Problem"))

    everyone.to_csv(report_xlsx.with_name(report_xlsx.stem + "_accounts.csv"), index=False)
    tmp = report_xlsx.with_name("~tmp_" + report_xlsx.name)
    wb.save(tmp)
    try:
        tmp.replace(report_xlsx)
        print(f"Saved {report_xlsx.name}: {len(table)} classified, {len(to_check['Review'])} to review, "
              f"{len(to_check['Label differences'])} label differences, {len(to_check['Non-core'])} non-core, "
              f"{(everyone['Result'] == 'not classified').sum()} not classified")
    except PermissionError:
        print(f"{report_xlsx.name} is open in Excel; saved as {tmp.name} instead")
