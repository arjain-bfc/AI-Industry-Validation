"""Phase 2: send each crawled account to Decision-1 and save the answers, one CSV line per call.

  build_state()   what the model reads about one account: company details and the best pages within a token budget
  crm_evidence()  CRM details (phone, ZIP, email domain) found on the site: proof the website is the company's
  run()           every account in the crawl store with no answer yet

Two files come out of a run:
  answers (.csv)        one line per call: the model's scores, the decisions made from them
  evidence log (.jsonl) one line per account: what happened at each stage (crawl, website text, model call,
                        website check, decision), what was sent to the model, and where and why it stopped

The questions are in questions.py, the API call in model_api.py, the decisions made from the answers in decide.py.
"""
import csv
import hashlib
import json
import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
import requests

import decide
import model_api
import page_rules
from questions import QUESTIONS, SEGMENTS
from crawl import append_line, cleared_by_hand, load_store, mark_site

# --- What the model reads ----------------------------------------------------------------------------------------
TOKEN_BUDGET = 24_000      # most tokens one call may use (75% of the model's ~32k)
RESERVED_TOKENS = 7_200    # the questions and company details
TOKENS_PER_WORD = 1.5      # website text (measured 1.24 on average, up to 1.45)
TOKENS_PER_PAGE = 90       # each page's path, title and JSON
MAX_WORDS_PER_PAGE = 3000  # one huge page can't use the whole budget
MAX_IMAGES_PER_PAGE = 20   # image labels per page
SKIP_PAGES = re.compile(r"(^|[/_.-])(privacy|terms|cookies?|accessibility|log-?in|sign-?in|cart|checkout)([/_.-]|$)",
                        re.I)
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
      - image labels already sent are left out too (logos repeat), and at most 20 new labels are sent
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
        label_and_title_words = sum(len(label.split()) for label in new_labels) + len((page["title"] or "").split())
        room_for_text = max(0, min(MAX_WORDS_PER_PAGE, words_that_fit - label_and_title_words))
        words = " ".join(new_lines).split()[:room_for_text]
        if not words and not new_labels:
            continue  # nothing new on this page
        sent = {"page": page["path"], "title": page["title"], "text": mark_own_facilities(" ".join(words))}
        if new_labels:
            sent["images"] = new_labels
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


def load_contacts(input_xlsx):
    """{account_id: {"phone", "email", "dba"}} from the input Excel."""
    df = pd.read_excel(input_xlsx, dtype=str).fillna("")
    contacts = {}
    for row in df.itertuples():
        if row.account_id.strip():
            contacts[row.account_id.strip().lower()] = {"phone": row.phone_number.strip(),
                                                        "email": row.email_address.strip().lower(),
                                                        "dba": row.doing_business_as.strip()}
    return contacts


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


# --- The answers file --------------------------------------------------------------------------------------------
FIELDS = ["account_id", "excel_row", "name", "url", "label", "status", "segment", "confidence", "how", "main_business",
          "site_match", "crm_evidence", "evidence", "pages_sent", "words_sent",
          *[f"p_{o}" for o in decide.OPTIONS], *[f"main_{s}" for s in SEGMENTS],
          "input_tokens", "seconds", "error_stage", "error", "run_at"]
QUESTIONS_VERSION = hashlib.md5(json.dumps(QUESTIONS, sort_keys=True).encode()).hexdigest()[:8]  # changes with wording


def answer_row(answers):
    """The model's answers (probabilities) plus the decisions made from them (decide.py)."""
    chosen, confidence, how = decide.segment(answers)
    main = decide.main_business(answers, chosen)
    probs = answers["industry"]["probabilities"]
    return {"segment": chosen, "confidence": round(confidence, 3), "how": how,
            "main_business": None if main is None else round(main, 3),
            "site_match": round(answers["site_match"]["noul"], 3),
            **{f"p_{o}": round(probs.get(o, 0), 3) for o in decide.OPTIONS},
            **{f"main_{s}": round(answers[f"main_{s}"]["noul"], 3) for s in SEGMENTS}}


def append_row(path, row):
    """Append one answer line and force it to disk (a crash never loses a paid call)."""
    new_file = not path.exists() or not path.stat().st_size
    if not new_file:
        with open(path, encoding="utf-8") as f:
            older = f.readline().strip().split(",") != FIELDS
        if older:  # written by an earlier version: rewritten once with today's columns (new ones left blank)
            pd.read_csv(path, dtype=str).reindex(columns=FIELDS).to_csv(path, index=False)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow(row)
        f.flush()
        os.fsync(f.fileno())


def load_answers(path):
    if not path.exists() or not path.stat().st_size:
        return pd.DataFrame(columns=FIELDS)
    return pd.read_csv(path, dtype={"account_id": str}, on_bad_lines="skip")


# --- The evidence log --------------------------------------------------------------------------------------------
# Stages, in order. An account that stops says at which one and why.
CRAWL, CONTENT, CALL, SITE, DECISION = "1 crawl", "2 website text", "3 model call", "4 website check", "5 decision"
NO_CONTENT = {"no_website": "no website in the CRM", "social_media_page_only": "only a social media page",
              "parked": "parked or for-sale domain", "dead_site": "the site no longer exists",
              "blocked": "the site refused the crawler", "network_blocked": "blocked by our own network filter",
              "unreachable": "the site didn't respond"}


def segment_evidence(state, most=4):
    """Pages sent to the model whose address names one of our segments, best first (e.g. '/24-hour-towing')."""
    pages = [p["page"] for p in state["website"]["pages"]]
    scored = sorted(((page_rules.segment_score(p), p) for p in pages if p != "/"), reverse=True)
    return [p for score, p in scored if score >= page_rules.SEGMENT_MATCH][:most]


SEGMENT_PHRASE = re.compile(r"\b(" + "|".join(sorted((re.escape(p) for g in page_rules.SEGMENT_PHRASES.values()
                                                     for p in g), key=len, reverse=True)) + r")s?\b", re.I)


def segment_phrases_found(state, most=8):
    """Our segment phrases (page_rules.SEGMENT_PHRASES) in the text sent, most frequent first: [(phrase, count)]."""
    text = " ".join(p["text"] for p in state["website"]["pages"])
    return Counter(m.group(1).lower() for m in SEGMENT_PHRASE.finditer(text)).most_common(most)


def call_error(err):
    """A model-call exception in plain words."""
    if isinstance(err, requests.Timeout):
        return "the model call timed out (no answer within 90 s)"
    if isinstance(err, requests.ConnectionError):
        return "could not reach the Decision-1 endpoint (network or VPN)"
    if isinstance(err, requests.HTTPError) and err.response is not None:
        code = err.response.status_code
        return {401: "API key rejected (401): check DECISION1_API_KEY", 403: "access denied (403): check the API key",
                408: "the endpoint timed out (408)", 429: "token quota or rate limit (429) after all retries",
                422: "the endpoint rejected the input (422): often too long or malformed"
                }.get(code, f"the endpoint returned HTTP {code}: {err.response.text[:150]}")
    return f"{type(err).__name__}: {str(err)[:200]}"


def short_error(text):
    """A crawl or call error in one line: the HTTP status or error name, not the stack trace."""
    text = re.sub(r"\bNone\b|\|\s*browser:", " ", str(text or "")).strip(" |")
    found = re.search(r"HTTP \d{3}[^\n.:]*|\b\d{3} (Client|Server) Error[^\n:]*|ERR_[A-Z_]+|timed? ?out|SSL[^\n.]*|"
                      r"certificate[^\n.]*|Blocked by [^\n.:]*|DNS[^\n.]*|[^\n]*not resolve[^\n]*", text, re.I)
    line = found.group(0) if found else text.strip().splitlines()[0] if text.strip() else ""
    return line.strip()[:160]


def crawl_signals(rec):
    """Stage 1: how the crawl went."""
    pages = rec.get("pages") or []
    home = next((p for p in pages if p["depth"] == 0), {})
    return {"status": rec["status"], "reason": rec.get("reason"), "attempts": rec.get("attempts"),
            "error": rec.get("error"), "pages_crawled": len(pages),
            "words_crawled": sum(len(p["text"].split()) for p in pages),
            "fetched_by": sorted({p.get("fetched_by") for p in pages} - {None}), "home_title": home.get("title"),
            "crawled_at": rec.get("crawled_at")}


def log_record(rec, stage, outcome, problem=None, state=None, row=None, crm=""):
    """One evidence-log line: everything known about an account at the stage it reached."""
    entry = {"account_id": rec["account_id"], "name": rec["company"].get("name", ""), "url": rec["url"],
             "logged_at": datetime.now().isoformat(timespec="seconds"), "stage_reached": stage, "outcome": outcome,
             "problem": problem, "crawl": crawl_signals(rec)}
    if state:
        sent = state["website"]["pages"]
        words = [len(p["text"].split()) for p in sent]
        entry["website_text"] = {
            "pages_sent": [{"page": p["page"], "words": w} for p, w in zip(sent, words)],
            "words_sent": sum(words),
            "estimated_tokens": int(RESERVED_TOKENS + sum(TOKENS_PER_PAGE + TOKENS_PER_WORD * w for w in words)),
            "pages_naming_our_segments": segment_evidence(state), "segment_phrases_found": segment_phrases_found(state),
            "domains_reached": state["website"].get("domains_reached")}
    if row and row.get("site_match") is not None:
        entry["website_check"] = {"site_match": row["site_match"], "fails_below": decide.WRONG_SITE_BELOW,
                                  "crm_details_on_site": crm or None, "cleared_by_hand": cleared_by_hand(rec),
                                  "result": "failed" if row["status"] == "wrong_site" else "passed"}
    if row and row.get("status") == "ok":
        entry["decision"] = {
            "model": model_api.MODELS["decision1"]["model"], "questions_version": QUESTIONS_VERSION, "input_tokens": row.get("input_tokens"),
            "probabilities": {o: row[f"p_{o}"] for o in decide.OPTIONS},
            "main_business_scores": {s: row[f"main_{s}"] for s in SEGMENTS},
            "rule": row["how"], "segment": decide.LABELS[row["segment"]], "confidence": row["confidence"],
            "confidence_band": decide.confidence_band(row["confidence"]),
            "main_business": decide.main_yes(row["main_business"]), "rationale": decide.rationale(row),
            "thresholds": {"other_from": decide.OTHER_FROM, "main_blocks_other": decide.MAIN_BLOCKS_OTHER,
                           "main_yes_from": decide.MAIN_YES_FROM}}
    if state:
        entry["sent_to_model"] = state  # the full input of the call (the questions: questions.py at that version)
    return entry


def not_sent_reason(rec, state, crm):
    """(stage, problem) for an account that gets no call, or None when it should be classified."""
    if rec["status"] in NO_CONTENT:
        retry = "" if rec["final"] else " (crawled again next run)"
        detail = short_error(rec.get("error"))
        detail = f" ({detail})" if detail and detail.lower() not in NO_CONTENT[rec["status"]] else ""
        return CRAWL, f"{NO_CONTENT[rec['status']]}{detail}{retry}"
    if not rec["final"]:
        return CRAWL, "crawl not finished (retried next run)"
    if state is None:
        return CONTENT, "pages were fetched but held no usable text (empty, scripts only, or legal pages)"
    if rec["status"] == "wrong_site" and not crm:
        score = (rec.get("site_check") or {}).get("score")
        return SITE, f"an earlier call found this isn't the company's website (score {score}); fix the CRM URL"
    return None


# --- The run -----------------------------------------------------------------------------------------------------
def handle(rec, state, crm, future, store_path):
    """(answer row, evidence-log line, what to print) for one finished call. Also records the website check in the
    store."""
    row = {"account_id": rec["account_id"], "excel_row": rec["excel_row"], "name": rec["company"].get("name", ""),
           "url": rec["url"], "label": rec.get("reference", {}).get("industry_types", ""), "crm_evidence": crm,
           "evidence": ", ".join(segment_evidence(state)), "pages_sent": len(state["website"]["pages"]),
           "words_sent": sum(len(p["text"].split()) for p in state["website"]["pages"]),
           "run_at": datetime.now().isoformat(timespec="seconds"), "error_stage": "", "error": ""}
    try:
        answers, tokens, seconds = future.result()
    except Exception as err:  # noqa: BLE001 (saved as failed; retried next run)
        row.update(status="failed", error_stage=CALL, error=call_error(err))
        return row, log_record(rec, CALL, "failed", row["error"], state, row, crm), f"FAILED: {row['error']}"
    try:
        row.update(answer_row(answers), input_tokens=tokens, seconds=round(seconds, 1))
    except Exception as err:  # noqa: BLE001 (an answer without the expected fields)
        row.update(status="failed", error_stage=DECISION, error=f"unexpected answer format: {err!r}"[:300])
        return row, log_record(rec, DECISION, "failed", row["error"], state, row, crm), f"FAILED: {row['error']}"
    if decide.wrong_site(row["site_match"], crm, cleared_by_hand(rec)):
        mark_site(store_path, rec, "wrong_site", by=model_api.MODELS["decision1"]["model"], score=row["site_match"])
        row["status"] = "wrong_site"
        problem = f"not the company's website (name match {row['site_match']:.0%}); fix the CRM URL"
        return row, log_record(rec, SITE, "not classified", problem, state, row, crm), f"WRONG WEBSITE ({problem})"
    row["status"] = "ok"
    if rec["status"] == "wrong_site":  # CRM details now prove it: clear the old mark
        mark_site(store_path, rec, "ok", by="crm_details")
    main = decide.main_yes(row["main_business"])
    said = f"{decide.LABELS[row['segment']]} {row['confidence']:.0%}" + (f", main business {main}" if main else "")
    return row, log_record(rec, DECISION, "classified", None, state, row, crm), said


def run(store_path, input_xlsx, answers_csv, evidence_log, workers=6, limit=None, redo_ids=(), on_progress=None):
    """Classify every account that needs it, and log every account's stages. Safe to stop and re-run: each answer
    is on disk before the next. on_progress() is called every 50 answers (the notebook rebuilds the report)."""
    store = load_store(store_path)
    contacts = load_contacts(input_xlsx)
    done = set(load_answers(answers_csv).query("status == 'ok'")["account_id"].str.lower())
    redo = {i.lower() for i in redo_ids}
    logged = {e["account_id"]: (e["crawl"].get("crawled_at"), e["stage_reached"])
              for e in load_store(evidence_log).values()}  # not logged again until something changes

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
        elif rec["account_id"] not in done or rec["account_id"] in redo:
            todo.append((rec, state, crm))
    todo = todo[:limit] if limit else todo
    print(f"{len(store)} accounts in {store_path.name} | {skipped} with no usable website (the Accounts sheet says why) | "
          f"{len(todo)} to classify")
    model_api.api_key()  # fails here, before any call, if DECISION1_API_KEY isn't set

    processed, failures_in_a_row, start = 0, 0, time.perf_counter()
    pool = ThreadPoolExecutor(workers)
    try:
        futures = {pool.submit(model_api.ask, state): (rec, state, crm) for rec, state, crm in todo}
        for future in as_completed(futures):
            row, entry, said = handle(*futures[future], future, store_path)
            append_row(answers_csv, row)
            append_line(evidence_log, entry)
            processed += 1
            failures_in_a_row = failures_in_a_row + 1 if row["status"] == "failed" else 0
            print(f"[{processed}/{len(todo)}] {row['name'][:40]} | {said}")
            if on_progress and processed % 50 == 0:
                on_progress()
            if failures_in_a_row >= 5:
                raise RuntimeError(f"5 failed calls in a row ({row['error']}): fix that, then re-run to continue")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        print(f"\n{processed} of {len(todo)} done in {(time.perf_counter() - start) / 60:.1f} min. "
              "Re-run to continue if stopped.")
