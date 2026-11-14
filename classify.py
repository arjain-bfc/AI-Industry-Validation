"""Phase 2: send each crawled account to Decision-1, decide, and save the result.

  run()   every account in the crawl store with no answer yet

For each account: build what the model reads (build_state, below), ask (model_api.py, with the questions in
questions.py), turn the 12 numbers into a decision (decide.py), then write one line to the answers file
and one to the evidence log (results.py). The website check's result is also written back to the crawl store.

The same company entered more than once in the CRM (same website, same name) gets one call, and every record of it
gets that answer (plan_calls). Safe to stop and re-run: each answer is on disk before the next.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd

import decide
import model_api
import page_rules
from accounts import load_contacts, same_company_key
from crawl import append_line, cleared_by_hand, load_store, mark_site
from results import (CALL, DECISION, FIELDS, PARTIAL_BOT_CHECK_UNSURE, SITE, answer_row, append_row, call_error,
                     load_answers, log_record, not_sent_reason, page_shown, segment_evidence)
from model_api import RESERVED_TOKENS, TOKEN_BUDGET, TOKENS_PER_PAGE, TOKENS_PER_WORD


# --- What the model reads about one account ---------------------------------------------------------------------------
MAX_WORDS_PER_PAGE = 3000  # one huge page can't use the whole budget


MAX_IMAGES_PER_PAGE = 20   # image labels per page


MAX_LINK_TITLES_PER_PAGE = 10  # link tooltips per page (crawl_worker.link_titles)


SKIP_PAGES = re.compile(r"(^|[/_.-])(privacy|terms|cookies?|accessibility|log-?in|sign-?in|cart|checkout)([/_.-]|$)",
                        re.I)


# A company's own shop under another name.
# "Our print shop Logos in Thread does the printing" reads to the model as if another company did the work. But a
# company's own shop under another name is still the company, so the text is changed to "our own print shop (Logos
# in Thread)". It is left alone when a word shows the shop belongs to someone else ("our partner print shop").
# The pattern is built from four plain parts:
#   OUR          "our" or "our own"
#   DESCRIPTION  up to five words before the kind of place ("print", "embroidery and screen print"), none of them a
#                word that makes it someone else's (NOT_OURS)
#   PLACE        shop, facility, plant, factory, workshop, studio, division, sister company or parent company
#   NAME         the shop's name: capitalised words (and "in", "of", "and", "&" between them), but not an ordinary
#                word that happens to start a sentence ("Our shop. We ...", "Our shop Please call")
NOT_OURS = (r"partner|preferred|trusted|recommended|vendor|supplier|contract\w*|network|third|outside|local|referral|"
            r"approved|certified|favou?rite|go-to|neighbou?rhood")


OUR = r"\b([Oo]ur) (?:own )?"


DESCRIPTION = r"(?:(?!(?:" + NOT_OURS + r")\b)[A-Za-z-]+ ){0,5}"


PLACE = r"(?:shop|facility|plant|factory|workshop|studio|division|sister company|parent company)"


SENTENCE_WORDS = (r"We|You|Our|The|This|That|It|They|Please|Call|Contact|Visit|Here|There|All|And|For|With|At|In|On|"
                  r"To|If|Is|Are|Every|Each|Since|Today|Now|Learn|See|Get|View")


NAME = r"((?!(?:" + SENTENCE_WORDS + r")\b)[A-Z][\w&'-]*(?: (?:[A-Z][\w&'-]*|in|of|and|&)){0,4})"


OWN_FACILITY = re.compile(OUR + "(" + DESCRIPTION + PLACE + "),? " + NAME)


def domain(url):
    """'https://www.Example.com/x' -> 'example.com'."""
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def rank_pages(pages):
    """The pages worth sending, best first: not empty, not legal, login or cart pages, in page_rules.order_pages's
    order."""
    usable = [p for p in pages if (p["text"].strip() or any(i["label"] for i in p["images"]))
              and not SKIP_PAGES.search(p["path"].split("?")[0])]
    return page_rules.order_pages(usable)


def mark_own_facilities(text):
    """'Our print shop Logos in Thread' -> 'Our own print shop (Logos in Thread)' (see OWN_FACILITY)."""
    return OWN_FACILITY.sub(lambda m: f"{m.group(1)} own {m.group(2)} ({m.group(3)})", text)


def build_state(record, dba=None):
    """What the model receives for one account: {"company": ..., "website": ...}, or None when the site has no
    usable text.

    The budget. One call may use 24,000 tokens (TOKEN_BUDGET). Our questions and the company details take about
    7,200, which leaves 16,800 for the website: roughly 11,000 words at 1.5 tokens a word. Pages go in best first
    (rank_pages) until that is used up. For each page:
      - lines already sent on a better page are left out (menus and footers repeat on every page)
      - image labels and link tooltips already sent are left out too (logos and menus repeat); at most 20 new image
        labels and 10 new link tooltips per page
      - at most 3,000 words of text, so one huge page can't use up the website's share
      - it costs 90 tokens for its address, title and layout, plus 1.5 for every word of text, labels and title
    """
    if record["status"] not in ("ok", "wrong_site"):
        return None
    tokens_left = TOKEN_BUDGET - RESERVED_TOKENS
    sent_lines, sent_labels, pages = set(), set(), []
    for page in rank_pages(record["pages"]):
        words_that_fit = int((tokens_left - TOKENS_PER_PAGE) / TOKENS_PER_WORD)
        if words_that_fit <= 0:
            break  # the budget is used up
        new_lines = [line.strip() for line in page["text"].splitlines()
                     if line.strip() and line.strip().lower() not in sent_lines]
        sent_lines.update(line.lower() for line in new_lines)
        new_labels = []
        for image in page["images"]:
            label = image["label"]
            if label and label.lower() not in sent_labels and label not in new_labels:
                new_labels.append(label)
        new_labels = new_labels[:MAX_IMAGES_PER_PAGE]
        sent_labels.update(label.lower() for label in new_labels)
        titles = page.get("link_titles", [])  # crawls before 2026-11-12 have none
        new_titles = [t for t in titles if t.lower() not in sent_labels][:MAX_LINK_TITLES_PER_PAGE]
        sent_labels.update(t.lower() for t in new_titles)
        label_and_title_words = (sum(len(label.split()) for label in new_labels + new_titles)
                                 + len((page["title"] or "").split()))
        room_for_text = max(0, min(MAX_WORDS_PER_PAGE, words_that_fit - label_and_title_words))
        words = " ".join(new_lines).split()[:room_for_text]
        if not words and not new_labels and not new_titles:
            continue  # nothing new on this page
        sent = {"page": page["path"], "title": page["title"], "text": mark_own_facilities(" ".join(words))}
        if new_labels:
            sent["images"] = new_labels
        if new_titles:
            sent["link_titles"] = new_titles
        pages.append(sent)
        tokens_left -= TOKENS_PER_PAGE + TOKENS_PER_WORD * (len(words) + label_and_title_words)
    if not pages:
        return None
    website = {"url": record["url"], "pages": pages}
    # When the crawl ended up on other web addresses than the one in the CRM (the site sent us on, e.g. after a
    # move to a new domain), they are listed so the website check can judge whether they're the same company.
    reached = sorted({domain(p["url"]) for p in record["pages"] if p.get("url")} - {""})
    if reached and reached != [domain(record["url"])]:
        website["domains_reached"] = reached
    company = dict(record["company"])
    if dba:
        company["doing_business_as"] = dba  # the DBA from the input file, for the website check
    return {"company": company, "website": website}


# --- CRM details that prove a site is the company's --------------------------------------------------------------
FREE_EMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "me.com", "msn.com",
              "live.com", "comcast.net", "att.net", "sbcglobal.net", "verizon.net", "bellsouth.net", "charter.net",
              "cox.net", "earthlink.net", "ymail.com", "protonmail.com", "mail.com", "frontier.com", "windstream.net"}


# The ZIP code in the CRM address: two capital letters (the state), a space, then five digits, optionally followed by
# a dash and four more: "Spring, TX 77377" or "TX 77377-1234". The five digits (in brackets) are what we look for.
ZIP = re.compile(r"\b[A-Z]{2}\s+(\d{5})(?:-\d{4})?\b")


def crm_evidence(record, contact):
    """CRM details found on the site, e.g. 'phone, ZIP 98034' ('' = none). Any one of them proves the website is the
    company's, whatever the model's website check says. Three checks:
      phone         the CRM phone's last 10 digits appear among the site's digits (spaces, dashes and brackets
                    ignored, so "(512) 555-0100" matches "512.555.0100")
      ZIP           the CRM address's 5-digit ZIP appears on the site as a number of its own (not inside a longer one)
      email domain  the CRM email is at the company's own domain (not gmail, yahoo, ...) and that domain is the website
                    or a domain the crawl reached"""
    text = " ".join(f"{p.get('title') or ''} {p['text']}" for p in record.get("pages") or [])
    found = []
    phone = re.sub(r"\D", "", contact.get("phone", ""))[-10:]  # \D = anything that isn't a digit
    if len(phone) == 10 and phone in re.sub(r"\D", "", text):
        found.append("phone")
    zip_code = ZIP.search(record["company"].get("location") or "")
    if zip_code and re.search(rf"(?<!\d){zip_code.group(1)}(?!\d)", text):  # no digit just before or after
        found.append(f"ZIP {zip_code.group(1)}")
    email = contact.get("email", "")
    email_domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    site_domains = {domain(record["url"]), *(domain(p.get("url")) for p in record["pages"])}
    if email_domain and email_domain not in FREE_EMAIL and email_domain in site_domains:
        found.append("email domain")
    return ", ".join(found)


# --- The run ----------------------------------------------------------------------------------------------------------
def account_fields(rec, state, crm, same_as=None):
    """The parts of an answer row that belong to the account itself (not to the model's answer)."""
    return {"account_id": rec["account_id"], "excel_row": rec["excel_row"], "name": rec["company"].get("name", ""),
            "url": rec["url"], "label": rec.get("reference", {}).get("industry_types", ""), "crm_evidence": crm,
            "evidence": ", ".join(segment_evidence(state)), "pages_sent": len(state["website"]["pages"]),
            "words_sent": sum(len(p["text"].split()) for p in state["website"]["pages"]),
            "run_at": datetime.now().isoformat(timespec="seconds"), "error_stage": "", "error": "", "same_as": same_as}


def handle(rec, state, crm, future, store_path, same_as=None):
    """(answer row, evidence-log line, what to print) for one finished call. Also records the website check in the
    store. same_as: the account whose call this is, when this account is the same company (it shares the call)."""
    row = account_fields(rec, state, crm, same_as)
    try:
        answers, tokens, seconds = future.result()
    except Exception as err:  # noqa: BLE001 (saved as failed; retried next run)
        row.update(status="failed", error_stage=CALL, error=call_error(err))
        return row, log_record(rec, CALL, "failed", row["error"], state, row, crm), f"FAILED: {row['error']}"
    try:
        row.update(answer_row(answers))
        if not same_as:  # the call's tokens and time are counted once, on the account that made it
            row.update(input_tokens=tokens, seconds=round(seconds, 1))
    except Exception as err:  # noqa: BLE001 (an answer without the expected fields)
        row.update(status="failed", error_stage=DECISION, error=f"unexpected answer format: {err!r}"[:300])
        return row, log_record(rec, DECISION, "failed", row["error"], state, row, crm), f"FAILED: {row['error']}"
    return judge(rec, state, crm, row, store_path)


def copy_answer(rec, state, crm, earlier, store_path):
    """An account whose company was answered in an earlier run (same_company_key): that answer, under this account,
    with no new call. The website check is still judged for this account (its own CRM details count)."""
    row = {f: None if pd.isna(earlier.get(f)) else earlier.get(f) for f in FIELDS}
    row.update(account_fields(rec, state, crm, same_as=earlier["account_id"]), input_tokens=None, seconds=None)
    return judge(rec, state, crm, row, store_path)


def judge(rec, state, crm, row, store_path):
    """The website check, then the decision: (answer row, evidence-log line, what to print)."""
    if decide.wrong_site(row["site_match"], crm, cleared_by_hand(rec)):
        mark_site(store_path, rec, "wrong_site", by=model_api.MODELS["decision1"]["model"], score=row["site_match"])
        row["status"] = "wrong_site"
        problem = f"website issue (site check {row['site_match']:.0%}): {page_shown(rec)}"
        return row, log_record(rec, SITE, "not classified", problem, state, row, crm), f"WEBSITE ISSUE ({problem})"
    row["status"] = "ok"
    if rec["status"] == "wrong_site":  # CRM details now prove it: clear the old mark
        mark_site(store_path, rec, "ok", by="crm_details")
    if decide.partial_bot_check_unsure(rec.get("reason"), row["probability"]):
        row["status"] = PARTIAL_BOT_CHECK_UNSURE
        problem = (f"a bot check let us read only the home page, and it wasn't enough to decide "
                   f"({decide.LABELS[row['segment']]} {row['probability']:.0%}); tried again on the next crawl")
        log = log_record(rec, DECISION, "not classified", problem, state, row, crm)
        return row, log, f"PARTIAL BOT CHECK ({problem})"
    main = decide.main_yes(row["main_business"])
    said = f"{decide.LABELS[row['segment']]} {row['probability']:.0%}" + (f", main business {main}" if main else "")
    return row, log_record(rec, DECISION, "classified", None, state, row, crm), said


def plan_calls(todo, store, answered, contacts, redo):
    """The same company entered more than once (same web address, same name and DBA: same_company_key) gets
    one call, shared by every record of it. A company already answered in an earlier run gets no call: its answer is
    copied. Returns (calls: one list of (record, state, crm) per company, copies: (record, state, crm, earlier row))."""
    def company(rec):
        return same_company_key(rec["url"], rec["company"].get("name"), contacts.get(rec["account_id"], {}).get("dba"))
    earlier = {company(rec): rec["account_id"] for rec in store.values()
               if rec["account_id"] in answered.index and rec["account_id"] not in redo}
    calls, copies = {}, []
    for rec, state, crm in todo:
        if company(rec) in earlier:
            copies.append((rec, state, crm, answered.loc[earlier[company(rec)]]))
        else:
            calls.setdefault(company(rec), []).append((rec, state, crm))
    return list(calls.values()), copies


def earlier_answers(answers_csv):
    """The latest answer of every account that has one, indexed by account_id. An account held back after a partial
    bot check counts as answered too: neither is sent again until the site is crawled again."""
    answered = load_answers(answers_csv)
    answered = answered[answered["status"].isin(["ok", PARTIAL_BOT_CHECK_UNSURE])]
    answered = answered.drop_duplicates("account_id", keep="last")
    return answered.set_index(answered["account_id"].str.lower())


def accounts_to_classify(store, contacts, answered, redo, evidence_log):
    """Go through the crawl store and sort the accounts: ([(record, state, crm)] that need an answer, how many
    can't be classified). An account that can't be classified (no website, a dead site, an earlier website issue)
    gets its evidence-log line here; it isn't logged again until something about it changes."""
    logged = {e["account_id"]: (e["crawl"].get("crawled_at"), e["stage_reached"])
              for e in load_store(evidence_log).values()}
    todo, skipped = [], 0
    for rec in sorted(store.values(), key=lambda r: r["excel_row"]):
        contact = contacts.get(rec["account_id"], {})
        state = build_state(rec, contact.get("dba")) if rec["final"] else None
        crm = crm_evidence(rec, contact) if state else ""
        stop = not_sent_reason(rec, state, crm)
        if stop:
            if logged.get(rec["account_id"]) != (rec.get("crawled_at"), stop[0]):
                append_line(evidence_log, log_record(rec, stop[0], "not classified", stop[1]))
            skipped += 1
        elif (rec["account_id"] not in answered.index or rec["account_id"] in redo
              or rec.get("crawled_at", "") > str(answered.loc[rec["account_id"], "run_at"])):  # crawled again since
            todo.append((rec, state, crm))
    return todo, skipped


def save(answers_csv, evidence_log, row, entry):
    """One result to disk: its line in the answers file and its line in the evidence log."""
    append_row(answers_csv, row)
    append_line(evidence_log, entry)


def run(store_path, input_xlsx, answers_csv, evidence_log, workers=6, limit=None, redo_ids=(), on_progress=None):
    """Classify every account that needs it, and log every account's stages. Safe to stop and re-run: each answer
    is on disk before the next. on_progress() is called every 50 answers (the notebook rebuilds the report).

    The steps: 1. sort the accounts into those that need an answer and those that can't be classified;
    2. group the same company's records, and copy answers a company already has; 3. make the calls, several at a
    time, saving each answer as it arrives."""
    store = load_store(store_path)
    contacts = load_contacts(input_xlsx)
    answered = earlier_answers(answers_csv)
    redo = {i.lower() for i in redo_ids}

    todo, skipped = accounts_to_classify(store, contacts, answered, redo, evidence_log)
    calls, copies = plan_calls(todo, store, answered, contacts, redo)
    calls = calls[:limit] if limit else calls
    total = len(copies) + sum(len(c) for c in calls)
    shared = f", {total - len(calls)} records of the same company share an answer" if total > len(calls) else ""
    print(f"{len(store)} accounts in {store_path.name} | {skipped} with no usable website (the Accounts sheet says "
          f"why) | {total} to classify: {len(calls)} calls{shared}")

    for rec, state, crm, earlier_row in copies:
        row, entry, said = copy_answer(rec, state, crm, earlier_row, store_path)
        save(answers_csv, evidence_log, row, entry)
        print(f"{row['name'][:40]} | {said} (same company as {earlier_row['name'][:40]}, answered earlier)")
    if not calls:
        return
    model_api.api_key()  # fails here, before any call, if DECISION1_API_KEY isn't set

    processed, failures_in_a_row, start = 0, 0, time.perf_counter()
    pool = ThreadPoolExecutor(workers)
    try:
        # one call per company, with its first record's input; every record of the company gets the answer
        futures = {pool.submit(model_api.ask, records[0][1]): records for records in calls}
        for future in as_completed(futures):
            records = futures[future]
            for n, (rec, state, crm) in enumerate(records):
                same_as = records[0][0]["account_id"] if n else None
                row, entry, said = handle(rec, state, crm, future, store_path, same_as)
                save(answers_csv, evidence_log, row, entry)
                shared = " (same company, shared call)" if n else ""
                print(f"[{processed + 1}/{len(calls)}] {row['name'][:40]} | {said}{shared}")
            processed += 1
            failures_in_a_row = failures_in_a_row + 1 if row["status"] == "failed" else 0
            if on_progress and processed % 50 == 0:
                on_progress()
            if failures_in_a_row >= 5:
                raise RuntimeError(f"5 failed calls in a row ({row['error']}): fix that, then re-run to continue")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        print(f"\n{processed} of {len(calls)} calls done in {(time.perf_counter() - start) / 60:.1f} min. "
              "Re-run to continue if stopped.")
