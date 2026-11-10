"""Phase 2's Excel report, rebuilt from the answers file, the evidence log and the crawl store (any time, as often as
you like). Also writes the Accounts sheet as a CSV next to the report.

Sheets:
  How it decides   the process in plain words, with the thresholds in use
  Guide            what every column means, the colours, and the thresholds in use
  Summary          accounts per segment and main business; agreement with the input file's label; stage counts
  Review           where we differ from the input file's label (ZoomInfo or CRM) AND our answer is unsure: the
                   ones to check. Your verdicts and notes are kept when the report is rebuilt
  Label differences  where we differ from the label and our answer is sure: worth a skim, above all the ones
                   we call Other. Verdicts and notes kept too. Accounts that match the label need no check
  Non-core         accounts that do a segment's work alongside a different main business (main business No)
  Accounts         every account in the input file (Output 1): the result, how sure, main business, match with the
                   label and a one-line rationale; or, if it wasn't classified, the stage it stopped at and why (the
                   evidence log, Output 2, has the full detail)
"""
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import classify
import crawl
import decide
from crawl import load_store

CRM_URL = ("https://beaconfunding.crm.dynamics.com/main.aspx?appid=c993cfe6-9fc6-4dc2-8749-69c92c6c4b53&forceUCI=1"
           "&pagetype=entityrecord&etn=account&id={account_id}")
VERDICT, NOTES = "Your verdict", "Notes"
KEY = {label.lower(): option for option, label in decide.LABELS.items()}  # "septic" -> "septic", ...


# --- Output 1: one row per classified account --------------------------------------------------------------------
def current_decision(answers, **bars):
    """The saved answers with segment, probability, rule and main business worked out again under today's thresholds
    (decide.redecide), so answers saved under earlier thresholds read the same as new ones. bars: a model's own
    other_from / main_blocks_other, used by the model comparison."""
    answers = answers.copy()
    decisions = [decide.redecide(row, **bars) for _, row in answers.iterrows()]  # (segment, probability, rule)
    answers["segment"] = [segment for segment, _, _ in decisions]
    answers["probability"] = [probability for _, probability, _ in decisions]
    answers["how"] = [rule for _, _, rule in decisions]
    # main business is the score for the chosen segment; none for Other
    answers["main_business"] = [None if segment == "other" else row[f"main_{segment}"]
                                for segment, (_, row) in zip(answers["segment"], answers.iterrows())]
    return answers


def accounts_table(answers, label_name):
    """Output 1: one readable row per classified account (its latest answer)."""
    ok = answers[answers["status"] == "ok"].drop_duplicates("account_id", keep="last")
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
    if has_label:  # an unsure account that also differs from the label: say so first
        review = [f"{label_name} says {label_text}; {why}" if why and m == "Mismatch" else why
                  for m, label_text, why in zip(match, label, review)]

    table = pd.DataFrame({"account_id": ok["account_id"], "Account": ok["name"], "Website": ok["url"]})
    if has_label:
        table[f"{label_name} industry"] = label
    table["Our industry"] = ours
    table["Probability"] = ok["probability"]
    table["Main business"] = ok["main_business"].map(decide.main_yes)
    if has_label:
        table["Match"] = match
        table[f"Our probability for the {label_name} industry"] = backing
    table["Rationale"] = ok.apply(decide.rationale, axis=1)
    table["Why review"] = review
    table["CRM"] = [CRM_URL.format(account_id=i) for i in ok["account_id"]]
    table["excel_row"] = ok["excel_row"]
    return table.sort_values("excel_row").drop(columns="excel_row")


# --- Output 2 (summary): the stage every account reached -------------------------------------------------------
def stage_of(rec, logged, latest):
    """(stage reached, outcome, problem) for one account. Taken from the evidence log when it has the account;
    for runs from before the evidence log, worked out from the answers file or the crawl store."""
    entry = logged.get(rec["account_id"])
    if entry:
        return entry["stage_reached"], entry["outcome"], entry["problem"] or ""
    if rec["account_id"] in latest.index:  # answered, but not in an evidence log
        status = latest.loc[rec["account_id"], "status"]
        if status == "ok":
            return classify.DECISION, "classified", ""
        if status == "wrong_site":
            return classify.SITE, "not classified", "not the company's website"
        error = latest.loc[rec["account_id"], "error"] if "error" in latest else ""
        return classify.CALL, status, classify.short_error(error)
    # never sent to the model: the crawl store says why
    usable = True if rec["status"] in ("ok", "wrong_site") else None
    stop = classify.not_sent_reason(rec, usable, "")
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
def summary_tables(table, stages, label_name):
    """{title: table} for the Summary sheet."""
    out = {}
    if not table.empty:
        out["Accounts per industry, by main business"] = pd.crosstab(
            table["Our industry"], table["Main business"].replace("", "(Other)"), margins=True, margins_name="Total")
        out["How sure"] = (table["Probability"].map(decide.how_sure).value_counts()
                             .reindex(["High", "Medium", "Low"]).fillna(0)
                             .astype(int).to_frame("accounts"))
        out["Where the accounts are"] = pd.DataFrame({"accounts": [
            len(table), *(len(part) for part in split_for_checking(table).values())]},
            index=["All classified (Accounts sheet)", *split_for_checking(table).keys()])
        col = f"{label_name} industry"
        if col in table:
            out[f"{label_name} industry (rows) vs ours (columns)"] = pd.crosstab(
                table[col].replace("", "(blank)"), table["Our industry"], margins=True, margins_name="Total")
            out[f"Same as {label_name}"] = table["Match"].replace("", "(no label)").value_counts().to_frame("accounts")
    if not stages.empty:
        out["Where accounts stopped"] = pd.crosstab(stages["Stage reached"], stages["Outcome"], margins=True,
                                                    margins_name="Total")
    return out


# --- Writing the workbook ----------------------------------------------------------------------------------------
def split_for_checking(table):
    """The sheets that need a look, from the Accounts table. Mostly only a difference from the label can need
    correcting: when our industry matches the CRM or ZoomInfo label, nothing changes in the CRM.
      Review              we differ from the label, and our answer is unsure (a reason in "Why review"); and any
                          segment under decide.CHECK_EVEN_IF_MATCH_BELOW (0.50), even matching the label: the model
                          thought something else was at least as likely, so the matching label proves nothing
      Label differences   we differ from the label, and our answer is sure
      Non-core            main business No: the company does the segment's work alongside a different main business
    With no label to compare with (an input file without an industry), Review holds every unsure answer instead."""
    if table.empty:
        return {"Review": table, "Label differences": table, "Non-core": table}
    unsure = table["Why review"] != ""
    if "Match" in table:
        differs = table["Match"] == "Mismatch"
        unlikely_segment = (table["Our industry"] != "Other") & (table["Probability"] < decide.CHECK_EVEN_IF_MATCH_BELOW)
        review, label_differences = table[(differs & unsure) | unlikely_segment], table[differs & ~unsure]
    else:
        review, label_differences = table[unsure], table.iloc[0:0]
    return {"Review": review.copy(), "Label differences": label_differences.copy(),
            "Non-core": table[table["Main business"] == "No"].copy()}


def previous_verdicts(path):
    """Verdicts and notes already typed on the Review and Label differences sheets, by account_id."""
    kept = []
    for sheet in ("Review", "Label differences"):
        try:
            old = pd.read_excel(path, sheet_name=sheet, dtype=str)
            kept.append(old.set_index("account_id")[[VERDICT, NOTES]].fillna(""))
        except (FileNotFoundError, ValueError, KeyError):
            pass
    return pd.concat(kept) if kept else pd.DataFrame(columns=[VERDICT, NOTES])


def add_verdict_columns(ws, part):
    """A Your verdict dropdown (our industries) and a yellow Notes column, for the sheets people work through."""
    col = get_column_letter(list(part.columns).index(VERDICT) + 1)
    dropdown = DataValidation(type="list", formula1='"' + ",".join(decide.LABELS.values()) + '"', allow_blank=True)
    ws.add_data_validation(dropdown)
    dropdown.add(f"{col}2:{col}{len(part) + 1}")
    for cell in ws[col][1:]:
        cell.fill = PatternFill("solid", fgColor="FFF2CC")


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


def write_sheet(ws, table, wrap=()):
    """Coloured header by group, sensible widths, frozen header row, filters. Confidences shown as percentages and
    coloured by band (High green, Medium yellow, Low red); Match/Mismatch and model agreement coloured too."""
    if table.empty:
        ws.append(["Nothing here yet"])
        return
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
            result_probability = column == "Probability" or column.endswith(" probability")  # not "Our probability for..."
            if result_probability or column.startswith("Our probability"):
                cell.number_format = "0%"
            if result_probability and isinstance(cell.value, (int, float)):
                cell.fill = PatternFill("solid", fgColor=BAND_FILLS[decide.how_sure(cell.value)])
            elif cell.value in fills:
                cell.fill = PatternFill("solid", fgColor=fills[cell.value])
    ws.freeze_panes = "C2"
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


def thresholds_guide(bars=None):
    """[(threshold, value and meaning)] for the Guide sheets. bars: a model's own Other bar / main-business net."""
    bars = {"other_from": decide.OTHER_FROM, "main_blocks_other": decide.MAIN_BLOCKS_OTHER, **(bars or {})}
    return [
        ("Other bar", f"{bars['other_from']:.2f}: Other only when the model leans Other with at least this probability"),
        ("Main-business safety net", f"{bars['main_blocks_other']:.2f}: Other only when every segment's main-business "
                                     "score is below this; otherwise that segment"),
        ("Main business Yes from", f"{decide.MAIN_YES_FROM:.2f}"),
        ("Probability colours", f"green = High ({decide.HIGH_FROM:.0%} or more), yellow = Medium "
                               f"({decide.MEDIUM_FROM:.0%} to {decide.HIGH_FROM:.0%}), red = Low (under "
                               f"{decide.MEDIUM_FROM:.0%}: a close call, so it is in the review queue)"),
        ("Website check", f"below {decide.WRONG_SITE_BELOW:.2f} the site isn't the company's (not classified), unless "
                          "the CRM phone, ZIP or email domain is on it"),
    ]


def report_guide(label_name):
    """The Guide sheet of the Phase 2 report: what each column means, and the thresholds in use."""
    label = f"{label_name} industry" if label_name else "Label"
    return {
        "Accounts sheet (Output 1): one row for every account in the input file": [
            ("Account, Website", "the CRM account and the website that was read"),
            (label, f"the industry the input file gives ({label_name or 'none'}); never used to decide"),
            ("Result", "our segment, or Other (the equipment we could finance); 'not classified' when the account "
                       "stopped before a decision (see Stopped at and Problem)"),
            ("Probability", "the model's probability for the result (0-100%). Coloured green, yellow or red by how "
                            "sure (see Thresholds)"),
            ("Main business", "Yes: the segment's work is the main business. No: done alongside another main "
                              "business. Blank for Other"),
            ("Match", f"our industry is the same as the {label_name or 'label'} industry"),
            (f"Our probability for the {label_name} industry" if label_name else "Our probability...",
             "how much the model backs the label's industry (0-100%)"),
            ("Rationale", "one line: what decided it and the number behind it, main business, the pages naming the "
                          "work (e.g. 'Towing, 92% sure. Main business: no. Pages: /24-hour-towing')"),
            ("Why review", "why the answer is unsure; blank = sure. Unsure answers that also differ from the label "
                           "are on the Review sheet"),
        ],
        "The sheets to work through": [
            ("Review", "we differ from the input file's label AND our answer is unsure (a close call, another "
                       "segment that looks like the main business, very little website text, a doubtful website). "
                       "These are the ones to check: pick a verdict"),
            ("Label differences", "we differ from the label and our answer is sure. Usually the label is wrong for our "
                                  "purposes (a home builder ZoomInfo calls Light Construction); skim them, above all "
                                  "the ones we call Other"),
            ("Accounts that match the label", "not listed anywhere to check: nothing would change in the CRM"),
            ("Non-core", "the company does a segment's work alongside a different main business (an auto shop that "
                         "also tows). Kept to count them over time; nothing to fix"),
        ],
        "Accounts not classified: the columns": [
            ("Stopped at", "the stage where it stopped: 1 crawl, 2 website text, 3 model call, 4 website check"),
            ("Problem", "why, in plain words (a dead or parked site, a site that refused us, a failed model call, "
                        "not the company's website, not crawled yet)"),
            ("Crawl, Pages crawled", "how the crawl ended (status and reason) and how many pages it saved"),
        ],
        "Colours": [
            ("Headers", "blue: the answers; orange: how sure; green: main business; grey: explanations"),
            ("Cells", "Probability: green High, yellow Medium, red Low. Match green, Mismatch red"),
        ],
        "Thresholds in use (decide.py)": thresholds_guide(),
    }


def every_account(table, stages, input_xlsx=None):
    """Output 1: every account in the input file, one row each. Classified accounts show their result; the others
    show the stage they stopped at and why. Accounts the crawl hasn't reached yet are listed as such."""
    results = stages.merge(table.drop(columns=["Account", "Website"]), on="account_id", how="left")
    if input_xlsx:
        accounts = crawl.load_accounts(input_xlsx)
        missing = accounts[~accounts["account_id"].isin(results["account_id"])]
        results = pd.concat([results, pd.DataFrame({
            "account_id": missing["account_id"], "Account": missing["name"], "Website": missing["url"].fillna(""),
            "Stage reached": "1 crawl", "Outcome": "not classified", "Problem": "not crawled yet (run Phase 1)",
            "excel_row": missing.index})], ignore_index=True)
    results["Result"] = results["Our industry"].fillna("not classified")
    first = ["account_id", "Account", "Website", *[c for c in table.columns if c.endswith(" industry")
                                                    and c != "Our industry" and not c.startswith("Our ")]]
    result_columns = ["Result", "Probability", "Main business", "Match",
                      *[c for c in table.columns if c.startswith("Our probability")], "Rationale", "Why review"]
    stopped = ["Stage reached", "Problem", "Crawl", "Pages crawled", "CRM"]
    ordered = [c for c in first + result_columns + stopped if c in results.columns]
    results["Stage reached"] = results["Stage reached"].where(results["Outcome"] != "classified", "")
    return results.sort_values("excel_row")[ordered].rename(columns={"Stage reached": "Stopped at"})


def build(store_path, answers_csv, report_xlsx, label_name="", evidence_log=None, input_xlsx=None):
    """Write the report and the accounts CSV. label_name = what the input file's industry_types column is
    ("ZoomInfo", "CRM"); "" when there's nothing to compare with. input_xlsx: the input file, so accounts the crawl
    hasn't reached yet are listed too."""
    store = load_store(store_path)
    answers = classify.load_answers(answers_csv)
    table = accounts_table(answers, label_name)
    stages = stage_log(store, answers, evidence_log, keep_order=True)
    everyone = every_account(table, stages, input_xlsx)
    to_check = split_for_checking(table)
    verdicts = previous_verdicts(report_xlsx)
    for name in ("Review", "Label differences"):  # the sheets people work through keep their verdicts and notes
        part = to_check[name]
        if not part.empty:
            kept = verdicts[~verdicts.index.duplicated(keep="last")].reindex(part["account_id"]).fillna("")
            part[VERDICT], part[NOTES] = kept[VERDICT].values, kept[NOTES].values

    wb = Workbook()
    ws = wb.active
    ws.title = "How it decides"
    ws.append(["Step", "What happens"])
    for step, text in decide.how_it_decides():
        ws.append([step, text])
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 28, 110
    for row in ws.iter_rows():
        row[0].font = Font(bold=True)
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    write_guide(wb.create_sheet("Guide"), report_guide(label_name))
    write_tables(wb.create_sheet("Summary"), summary_tables(table, stages, label_name))

    for name, part in to_check.items():
        ws = wb.create_sheet(name)
        if name == "Label differences":
            part = part.drop(columns="Why review")  # sure answers: no reasons to show
        if name == "Non-core":  # a list to count, not to check: the answer, how sure, and why
            part = part.drop(columns=[c for c in part.columns if c in ("Why review", "Main business", "Match")
                                      or c.startswith("Our probability")])
        write_sheet(ws, part, ("Rationale", "Why review", NOTES))
        if VERDICT in part:
            add_verdict_columns(ws, part)
    write_sheet(wb.create_sheet("Accounts"), everyone, ("Rationale", "Why review", "Problem"))

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
