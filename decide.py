"""Every rule and threshold that turns the model's answer into a decision, in one place. Read this file to know
exactly how an account is decided; the numbers below are the ones in use.

WHAT THE MODEL GIVES US (one call per account; the wording of the questions is in questions.py)
  industry     a probability for each of the five segments and for Other (they add up to 1), and its own pick
  main_<seg>   for each segment, the probability that this segment's work is the company's MAIN business
  site_match   the probability that the website really is the company's

HOW AN ACCOUNT IS DECIDED, in order
  1. Website check (wrong_site)
       site_match under 0.15 (WRONG_SITE_BELOW)            -> not the company's website: not classified, and listed
                                                              for CRM clean-up
       ...unless the CRM phone, ZIP or email domain is on the site, or someone cleared the site by hand
  2. Segment (choose)
       the model picked a segment                         -> that segment
       the model picked Other, but two safety nets come first, because losing a real business costs more than a
       wasted sales call:
         a. some segment's main-business score is 0.50 or more (MAIN_BLOCKS_OTHER)   -> that segment
         b. its probability for Other is under 0.80 (OTHER_FROM)                       -> its likeliest segment
       only when both pass                                 -> Other
       So Other needs: the model leans Other, at least 80% sure, AND every main-business score under 50%.
  3. Main business (main_yes)
       the chosen segment's main-business score is 0.40 or more (MAIN_YES_FROM)   -> Yes; otherwise No; blank for
       Other. No means the company does the work alongside a different main business ("non-core")
  4. How sure (how_sure): the model's probability for the result, shown as the colour of the Probability cell
       High    0.90 or more (HIGH_FROM)        green
       Medium  0.75 to 0.90 (MEDIUM_FROM)      yellow
       Low     under 0.75: a close call        red
       The same measure for every account, whichever rule decided it: when a safety net overrode Other, it is the
       chosen segment's probability (usually low, so it shows red)
  5. Unsure? (review_reasons): any of these makes an answer unsure
       a close call (probability under 0.75)
       a segment other than ours has a main-business score of 0.40 or more
       site_match under 0.40 (SITE_UNSURE_BELOW) with no CRM details on the site
       fewer than 150 words of website text were sent (THIN_BELOW_WORDS)
  6. What gets checked (report.split_for_checking): only a difference from the input file's label (ZoomInfo or
     CRM industry) can need correcting
       we differ from the label AND we are unsure   -> Review sheet (the ones a person should check)
       we differ from the label and we are sure     -> Label differences sheet (worth a skim)
       main business No                             -> Non-core sheet (a count to track, nothing to fix)
       we match the label                           -> nothing to check
       no label to compare with                     -> every unsure answer goes to Review

WHY THE NUMBERS ARE WHAT THEY ARE (details and dates in DECISIONS.md)
  0.15 website check   wrong websites score about 0.00-0.10, real ones 0.6 and up; 0.20 rejected real sites
  0.80 Other bar       true Others mostly score 0.95+ (92 of 132 on 2026-11-09); 0.75-0.80 held as many real
                       businesses as true Others, so the bar leans to keeping them
  0.50 safety net      true Others' highest main-business score was 0.27 at most, brokers and dealers included
  0.40 main Yes        side lines score about 0.0-0.1, real main businesses 0.5-1.0
  0.90 / 0.75 bands    the earlier lines on the model's confidence field (0.85 and 0.70) put on the probability scale
                       (0.70 -> 0.75, 0.85 -> 0.875, rounded up to 0.90); one measure in every column
  In 0.05 steps on purpose: the model's scores move by up to 0.2 between calls, so finer bars only follow noise.

OTHER NUMBERS, AND WHERE THEY LIVE
  crawl limits (pages per site, seconds per site, workers)   crawl.py, CRAWL and PASSES
  which pages are fetched and sent first                     page_rules.py
  how much website text one call may carry (token budget)    classify.py, TOKEN_BUDGET and the lines after it
  a model's own Other bar and safety net (Jev: 0.70, 0.40)   compare_models.ipynb, THRESHOLDS
"""
import pandas as pd

from questions import SEGMENTS

OPTIONS = [*SEGMENTS, "other"]
LABELS = {"decorated_apparel": "Decorated Apparel", "landscape_hardscape": "Landscape/Hardscape",
          "light_construction": "Light Construction", "septic": "Septic", "towing": "Towing", "other": "Other"}

# --- The thresholds (what each does and why: see the top of this file) ------------------------------------------
WRONG_SITE_BELOW = 0.15   # 1. website check: under this, not the company's website
OTHER_FROM = 0.80         # 2b. Other bar: Other only when the model is at least this sure
MAIN_BLOCKS_OTHER = 0.50  # 2a. safety net: a main-business score this high gets that segment, never Other
MAIN_YES_FROM = 0.40      # 3. main business Yes from here
HIGH_FROM = 0.90          # 4. probability High (green) from here...
MEDIUM_FROM = 0.75        #    ...Medium (yellow) from here; under it Low (red), a close call
SITE_UNSURE_BELOW = 0.40  # 5. unsure: website check under this (and no CRM details on the site)
THIN_BELOW_WORDS = 150    # 5. unsure: fewer words of website text than this were sent

# Which rule decided the segment (choose()'s third value; shown in the rationale and the evidence log)
MODEL_PICK, OTHER_BAR, MAIN_NET, SURE_OTHER = "model's pick", "Other bar", "main-business safety net", "sure Other"


# --- 1. Website check ------------------------------------------------------------------------------------------
def wrong_site(site_match, crm_evidence, cleared_by_hand=False):
    """True when the site isn't the company's. CRM phone, ZIP or email domain on the site always passes it, and so
    does a site someone cleared by hand."""
    return site_match < WRONG_SITE_BELOW and not crm_evidence and not cleared_by_hand


# --- 2. Segment ------------------------------------------------------------------------------------------------
def choose(model_pick, probabilities, main_scores, other_from=OTHER_FROM, main_blocks_other=MAIN_BLOCKS_OTHER):
    """The segment rule, in one place: (segment, its probability, which rule decided it).

    The model's own pick stands, except that Other must pass two checks first:
      1. main-business safety net: if some segment's main-business score is main_blocks_other or more, that segment
      2. Other bar: if the model's probability for Other is under other_from, the likeliest segment
    Only when both pass is the answer Other. The probability returned is always the chosen answer's own; when a
    check overrides Other it is low, so the account lands in the review queue."""
    if model_pick != "other":
        return model_pick, probabilities[model_pick], MODEL_PICK
    top_main = max(SEGMENTS, key=main_scores.get)
    if main_scores[top_main] >= main_blocks_other:
        return top_main, probabilities[top_main], MAIN_NET
    if probabilities["other"] < other_from:
        likeliest = max(SEGMENTS, key=probabilities.get)
        return likeliest, probabilities[likeliest], OTHER_BAR
    return "other", probabilities["other"], SURE_OTHER


def segment(answers):
    """choose() on a fresh answer from the model."""
    industry = answers["industry"]
    probabilities = {o: industry["probabilities"].get(o, 0) for o in OPTIONS}
    main_scores = {s: answers[f"main_{s}"]["noul"] for s in SEGMENTS}
    return choose(industry["choice"], probabilities, main_scores)


def redecide(row, other_from=OTHER_FROM, main_blocks_other=MAIN_BLOCKS_OTHER):
    """choose() again on a saved answers row, with today's thresholds (or a model's own, in the comparison), so a
    threshold change applies to earlier answers without new calls.
    The answers file doesn't keep the model's own pick, so it is read back: if the likeliest option is Other, the
    model picked Other; otherwise it picked the segment we saved (or, if we saved an override, its likeliest
    segment)."""
    probabilities = {o: row[f"p_{o}"] for o in OPTIONS}
    main_scores = {s: row[f"main_{s}"] for s in SEGMENTS}
    saved_as_model_pick = pd.isna(row.get("how")) or row.get("how") in ("", MODEL_PICK)  # older files have no "how"
    if max(probabilities, key=probabilities.get) == "other":
        model_pick = "other"
    elif row["segment"] != "other" and saved_as_model_pick:
        model_pick = row["segment"]
    else:
        model_pick = max(SEGMENTS, key=probabilities.get)
    return choose(model_pick, probabilities, main_scores, other_from, main_blocks_other)


# --- 3. Main business ------------------------------------------------------------------------------------------
def main_business(answers, chosen):
    """main_<segment> for the chosen segment (0-1), None for Other."""
    return None if chosen == "other" else answers[f"main_{chosen}"]["noul"]


def main_yes(value):
    """'Yes' / 'No', '' for Other."""
    return "" if value is None or pd.isna(value) else "Yes" if value >= MAIN_YES_FROM else "No"


# --- 4. How sure, and why ----------------------------------------------------------------------------------------
def how_sure(probability):
    """'High', 'Medium' or 'Low' for the result's probability (Low = a close call)."""
    return "High" if probability >= HIGH_FROM else "Medium" if probability >= MEDIUM_FROM else "Low"


def runner_up(row):
    """The likeliest option other than our answer, e.g. 'Other (36%)'. (When a threshold kept a segment, Other is
    the likeliest option of all, so the runner-up is Other, not the second on the list.)"""
    others = [o for o in OPTIONS if o != row["segment"]]
    second = max(others, key=lambda o: row[f"p_{o}"])
    return f"{LABELS[second]} ({row[f'p_{second}']:.0%})"


def rationale(row, other_from=OTHER_FROM):
    """The reason for the answer in one short line: what decided it, the number behind it, and the evidence.
      Towing, 92% sure. Main business: no. Pages: /24-hour-towing
      Towing: model leaned Other (75%, under the 80% bar). Main business: no
      Light Construction: looks like its main business (56%), so not Other. Pages: /site-work
      Other: 97% sure, no sign of our equipment
    "Website confirmed by CRM phone" is added when the model's website check was low and CRM details saved it."""
    segment, label = row["segment"], LABELS[row["segment"]]
    how = row.get("how") or MODEL_PICK
    if segment == "other":
        parts = [f"Other: {row['p_other']:.0%} sure, no sign of our equipment"]
    elif how == OTHER_BAR:
        parts = [f"{label}: model leaned Other ({row['p_other']:.0%}, under the {other_from:.0%} bar)"]
    elif how == MAIN_NET:
        parts = [f"{label}: looks like its main business ({row[f'main_{segment}']:.0%}), so not Other"]
    else:
        parts = [f"{label}, {row['probability']:.0%} sure"]
    if segment != "other":
        parts.append(f"Main business: {main_yes(row['main_business']).lower()}")
    pages = row.get("evidence") if isinstance(row.get("evidence"), str) else ""
    if pages:
        parts.append(f"Pages: {pages}")
    crm = row.get("crm_evidence") if isinstance(row.get("crm_evidence"), str) else ""
    if crm and row["site_match"] < SITE_UNSURE_BELOW:
        parts.append(f"Website confirmed by CRM {crm}")
    return ". ".join(parts)


# --- 5. Review -------------------------------------------------------------------------------------------------
def review_reasons(row):
    """Why an answer deserves a second look, e.g. 'close call with Other (36%); little website text'. '' = none.
    Each reason, in order:
      close call                   probability under 75% (shown red); names the runner-up, e.g. "Other (36%)"
      another segment looks main   a segment other than ours has a main-business score of 40% or more
      website may not be theirs    website check under 40% and no CRM details on the site
      little website text          fewer than 150 words were sent to the model
    Disagreement with the input file's label is added by the report."""
    reasons = []
    if row["probability"] < MEDIUM_FROM:
        reasons.append(f"close call with {runner_up(row)}")
    other_main = [s for s in SEGMENTS if s != row["segment"] and row[f"main_{s}"] >= MAIN_YES_FROM]
    if other_main:
        top = max(other_main, key=lambda s: row[f"main_{s}"])
        reasons.append(f"{LABELS[top]} looks like its main business")
    evidence = row.get("crm_evidence")
    if row["site_match"] < SITE_UNSURE_BELOW and not (isinstance(evidence, str) and evidence.strip()):
        reasons.append(f"website may not be the company's (site check {row['site_match']:.2f})")
    if row["words_sent"] < THIN_BELOW_WORDS:
        reasons.append(f"little website text ({row['words_sent']} words)")
    return "; ".join(reasons)


# --- The process in plain words (first sheet of the report) -----------------------------------------------------
def how_it_decides():
    """[(step, what happens)] for the report."""
    return [
        ("1. Read the website", "Phase 1 crawls the company's website (its pages and sitemap, most informative first). "
         "Phase 2 sends the best pages (home, about, services, pages naming our segments) to Decision-1 with our "
         "questions. Accounts without a usable website are not classified; the Accounts sheet says where they stopped and why."),
        ("2. Is it their website?", f"Decision-1 checks that the site belongs to the company, by business name. If it "
         f"clearly doesn't (score under {WRONG_SITE_BELOW:.0%}), the account is not classified. The CRM phone number, "
         "ZIP code or email domain on the site always passes this check."),
        ("3. Which segment?", "A company gets one of our five segments when it does that segment's work itself, the "
         "kind of work done with equipment we finance (embroidery and print machines, landscape and light-construction "
         "equipment, septic and vacuum trucks, tow trucks). Work it only arranges, resells or hands to another company "
         "doesn't count, and neither does only selling or repairing the equipment. The label in the CRM or ZoomInfo "
         "is not used."),
        ("4. Other only when sure", f"Other means we would not finance equipment for this company. A missed customer "
         f"costs more than an extra call, so Other needs at least {OTHER_FROM:.0%} from Decision-1; anything less goes "
         f"to the likeliest segment. And if a segment looks like the company's main business ({MAIN_BLOCKS_OTHER:.0%} "
         "or more), it gets that segment, never Other."),
        ("5. Main business", f"Yes: the segment's work is the company's main business. No: the company does the work, "
         f"but alongside a different main business (an auto repair shop that also tows). Yes from "
         f"{MAIN_YES_FROM:.0%}. Blank for Other."),
        ("6. How sure, and rationale", f"The model's probability for the result. High: {HIGH_FROM:.0%}+, Medium: "
         f"{MEDIUM_FROM:.0%}-{HIGH_FROM:.0%}, Low: below that (a close call). Each account has a short rationale built from the same numbers: which rule "
         "decided it, main business, the pages naming the work, and how the website was confirmed."),
        ("7. What to check", "Only a difference from the CRM or ZoomInfo label can need correcting; accounts that "
         "match are left alone. Review lists the differences where our answer is unsure (a close call, a different "
         "segment that looks like the main business, a doubtful website, very little website text). Label "
         "differences lists the differences where our answer is sure. Non-core lists companies that do a segment's "
         "work alongside a different main business. Verdicts and notes are kept when the report is rebuilt."),
    ]
