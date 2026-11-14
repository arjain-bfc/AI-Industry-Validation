"""What Phase 2 writes: the answers file and the evidence log.

The answers file (.csv): one line per model call, with the model's numbers and the decision made from them.
  answer_row()    the model's 12 numbers, plus the decision (decide.py)
  append_row()    add one line and force it to disk (a crash never loses a paid call)
  load_answers()  read the file back
A line's status says what became of the call:
  ok                         classified
  wrong_site                 the website check failed (a website issue): not classified
  partial_bot_check_unsure   a bot check let the crawl read only the home page, and the model wasn't sure enough
                             from it: not classified, asked again once the site is crawled again
  failed                     the call or its answer failed: asked again on the next run

The evidence log (.jsonl): one line per account, saying how far it got and why. An account goes through five
stages: crawl, website text, model call, website check, decision. The log keeps what happened at each one, what was
sent to the model, and, when an account stopped, where and why in plain words. The report's Not classified sheet
and the Accounts sheet's last columns are read from it.
  log_record()       one line: everything known about an account at the stage it reached
  not_sent_reason()  why an account gets no model call (no website, a dead site, an earlier website issue, ...)
  call_error()       a failed model call in plain words
"""
import csv
import os
import re
from collections import Counter
from datetime import datetime

import pandas as pd
import requests

import decide
import model_api
import page_rules
from crawl import cleared_by_hand, may_come_back
from model_api import RESERVED_TOKENS, TOKENS_PER_PAGE, TOKENS_PER_WORD
from questions import QUESTIONS_VERSION, SEGMENTS


# --- The answers file -------------------------------------------------------------------------------------------------
FIELDS = ["account_id", "excel_row", "name", "url", "label", "status", "segment", "probability", "how", "main_business",
          "site_match", "crm_evidence", "evidence", "pages_sent", "words_sent",
          *[f"p_{o}" for o in decide.OPTIONS], *[f"main_{s}" for s in SEGMENTS],
          "input_tokens", "seconds", "error_stage", "error", "same_as", "run_at"]


PARTIAL_BOT_CHECK_UNSURE = "partial_bot_check_unsure"  # answer status: bot check, and the home page didn't settle it


def answer_row(answers):
    """One answer line: the model's 12 numbers plus the decisions made from them (decide.py).
      site_match                       the website check (yes/no): 1 probability
      p_<segment>, p_other             the industry question (one choice out of 6): 6 probabilities adding up to 1
      main_<segment>                   the main-business question, asked once per segment (yes/no): 5 probabilities,
                                       each on its own
      segment, probability, how        the decision: the AI predicted industry, its probability, which rule decided
      main_business                    the chosen segment's main_<segment> score (None for Other)"""
    chosen, probability, how = decide.segment(answers)
    main = decide.main_business(answers, chosen)
    probs = answers["industry"]["probabilities"]
    return {"segment": chosen, "probability": round(probability, 3), "how": how,
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


# --- The evidence log -------------------------------------------------------------------------------------------------
# Stages, in order. An account that stops says at which one and why.
CRAWL, CONTENT, CALL, SITE, DECISION = "1 crawl", "2 website text", "3 model call", "4 website check", "5 decision"


NO_CONTENT = {"no_website": "no website in the CRM", "social_media_page_only": "only a social media or listing page",
              "parked": "parked or for-sale domain", "dead_site": "the site no longer exists or is only a placeholder",
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
        entry["website_check"] = {"site_match": row["site_match"], "fails_below": decide.WRONG_SITE_THRESHOLD,
                                  "crm_details_on_site": crm or None, "cleared_by_hand": cleared_by_hand(rec),
                                  "result": "failed" if row["status"] == "wrong_site" else "passed"}
    if row and row.get("status") == "ok":
        entry["decision"] = {
            "model": model_api.MODELS["decision1"]["model"], "questions_version": QUESTIONS_VERSION,
            "input_tokens": row.get("input_tokens"),
            "probabilities": {o: row[f"p_{o}"] for o in decide.OPTIONS},
            "main_business_scores": {s: row[f"main_{s}"] for s in SEGMENTS},
            "rule": row["how"], "segment": decide.LABELS[row["segment"]], "probability": row["probability"],
            "how_sure": decide.how_sure(row["probability"]),
            "main_business": decide.main_yes(row["main_business"]), "rationale": decide.rationale(row),
            "thresholds": {"other_threshold": decide.OTHER_THRESHOLD,
                           "safety_net_threshold": decide.SAFETY_NET_THRESHOLD,
                           "main_business_threshold": decide.MAIN_BUSINESS_THRESHOLD}}
    if state:
        entry["sent_to_model"] = state  # the full input of the call (the questions: questions.py at that version)
    return entry


def page_shown(rec):
    """What the site's home page calls itself, e.g. 'the page shows "500 Internal Server Error"': with the site
    check score, enough to see what the website issue is (another business, an error or empty page, a placeholder,
    a domain taken over or sold)."""
    pages = rec.get("pages") or []
    home = next((p for p in pages if p["depth"] == 0), pages[0] if pages else {})
    title = " ".join((home.get("title") or "").split())[:70]
    return f'the page shows "{title}"' if title else "the page has no title"


def not_sent_reason(rec, state, crm):
    """(stage, problem) for an account that gets no call, or None when it should be classified."""
    if rec["status"] in NO_CONTENT:
        retry = " (tried again on the next crawl)" if may_come_back(rec) else ""
        detail = short_error(rec.get("error"))
        detail = f" ({detail})" if detail and detail.lower() not in NO_CONTENT[rec["status"]] else ""
        return CRAWL, f"{NO_CONTENT[rec['status']]}{detail}{retry}"
    if not rec["final"]:
        return CRAWL, "crawl not finished: it has tries left (run Phase 1 again)"
    if state is None:
        return CONTENT, "pages were fetched but held no usable text (empty, scripts only, or legal pages)"
    if rec["status"] == "wrong_site" and not crm:
        score = (rec.get("site_check") or {}).get("score")
        score = f"{score:.0%}" if isinstance(score, (int, float)) else "?"
        return SITE, (f"website issue (site check {score}): {page_shown(rec)}; checked again when the CRM web address "
                      "changes, or with RECHECK_WEBSITE_ISSUES in Phase 1")
    return None
