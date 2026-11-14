"""Every rule and threshold that turns the model's answer into a decision, in one place. Read this file to know
exactly how an account is decided; the numbers below are the ones in use.

WHAT THE MODEL GIVES US: one call per account, 7 questions, 12 numbers (wording in questions.py)
  In:  the company (CRM name, DBA, address) and its best website pages (address, title, text, image labels)
  Out:                                                   kind                 numbers
    site_match     is this website the company's?        yes/no               1 probability
    industry       which of 6 options: the 5 segments    choose one of 6      6 probabilities that add up to 1
                   or Other? (whose equipment it uses)                         (p_decorated_apparel ... p_other)
    main_<seg> x5  is this segment's work the company's  yes/no, once per     5 probabilities, each on its own:
                   MAIN business?                        segment              they don't add up; several can be
                                                                              high, or all low
  The industry question and the five main-business questions are separate. The industry question picks one option
  out of six; each main-business question is asked for its own segment, whatever industry comes out. The decision
  below combines them. report_guide.what_the_model_answers() lays out the same in tables, with examples.

HOW AN ACCOUNT IS DECIDED, in order
  1. Website check (wrong_site)
       site_match under 0.15 (WRONG_SITE_THRESHOLD)            -> a "website issue": the site doesn't show this
                                                              company (another business, an error or empty page, a
                                                              placeholder, a domain taken over or sold). Not
                                                              classified; checked again when the CRM web address
                                                              changes (or with Phase 1's RECHECK_WEBSITE_ISSUES)
       ...unless the CRM phone, ZIP or email domain is on the site, or someone cleared the site by hand
     Partial bot check (partial_bot_check_unsure)
       a bot check let the crawl read only the home page (crawl reason partial_bot_check), and the probability
       for the result is under 0.75 (PARTIAL_BOT_CHECK_THRESHOLD)  -> not classified; the next crawl tries the site
                                                                   again, one page at a time
       0.75 or more: the home page was enough, and the answer stands
  2. Segment (choose)
       the model picked a segment                         -> that segment
       the model picked Other, but two safety nets come first, because losing a real business costs more than a
       wasted sales call:
         a. some segment's main-business score is 0.50 or more (SAFETY_NET_THRESHOLD)     -> that segment
         b. its probability for Other is under 0.80 (OTHER_THRESHOLD)       -> its likeliest segment
       only when both pass                                 -> Other
       So Other needs: the model leans Other, at least 80% sure, AND every main-business score under 50%.
  3. Main business (main_yes)
       the chosen segment's main-business score is 0.40 or more (MAIN_BUSINESS_THRESHOLD)   -> Yes; otherwise No;
       blank for Other. No means the company does the work alongside a different main business ("non-core")
  4. How sure (how_sure): the model's probability for the result, shown as the colour of the Probability cell
       High    0.90 or more (HIGH_BAND)        green
       Medium  0.75 to 0.90 (MEDIUM_BAND)      yellow
       Low     under 0.75: a close call        red
       The same measure for every account, whichever rule decided it: when a safety net overrode Other, it is the
       chosen segment's probability (usually low, so it shows red)
  5. Doubts (review_reasons): shown in the "Doubts" column, so a reader sees what could be wrong with an answer
       a close call (probability under 0.75)
       a segment other than ours has a main-business score of 0.40 or more
       site_match under 0.40 (UNSURE_SITE_THRESHOLD) with no CRM details on the site
       fewer than 150 words of website text were sent (THIN_SITE_WORDS)
     Doubts explain an answer; they don't decide which sheet it goes to.
  6. What gets checked (report.split_for_checking): the thresholds above already settle each answer, so a person
     only checks a segment the model itself found unlikely. An Other is never unlikely (it needs 0.80).
       segment differs from the label, probability under 0.50 (REVIEW_THRESHOLD_DIFFERS)  -> Review sheet
       segment matches the label, probability under 0.30 (REVIEW_THRESHOLD_MATCHES)       -> Review sheet
       any other difference from the label                                              -> Label differences (a skim)
       main business No                                                                 -> Non-core (a count to track)
       everything else                                                                  -> nothing to check
       no label to compare with                                                         -> segments under 0.50 to Review

WHY THE NUMBERS ARE WHAT THEY ARE (details and dates in DECISIONS.md)
  0.15 website check   wrong websites score about 0.00-0.20, real ones mostly 0.6 and up; the lowest real site seen
                       scored 0.24, so the bar stays low
  0.80 Other bar       true Others mostly score 0.95+ (92 of 132 on 2026-11-09); 0.75-0.80 held as many real
                       businesses as true Others, so the bar leans to keeping them
  0.50 safety net      true Others' highest main-business score was 0.27 at most, brokers and dealers included
  0.40 main Yes        non-core work scores about 0.0-0.1, real main businesses 0.5-1.0
  0.90 / 0.75 bands    the earlier lines on the model's confidence field (0.85 and 0.70) put on the probability scale
                       (0.70 -> 0.75, 0.85 -> 0.875, rounded up to 0.90); one measure in every column
  0.50 / 0.30 review  under 0.50 the model found another option (usually Other) at least as likely. A match with
                       the label is less suspicious, so only seriously low ones are checked: under 0.30 they were all
                       accounts the model leaned Other on (a real estate firm, a subcontractor network; 2026-11-10)
  In 0.05 steps on purpose: the model's scores move by up to 0.2 between calls, so finer bars only follow noise.

OTHER NUMBERS, AND WHERE THEY LIVE
  crawl limits (pages per site, seconds per site, workers)   crawl.py, CRAWL and PASSES
  which pages are fetched and sent first                     page_rules.py
  how much website text one call may carry (token budget)    model_api.py, TOKEN_BUDGET and the lines after it
  a model's own Other bar and safety net (Jev: 0.70, 0.40)   compare_models.ipynb, THRESHOLDS
"""
import pandas as pd

from questions import SEGMENTS


OPTIONS = [*SEGMENTS, "other"]


LABELS = {"decorated_apparel": "Decorated Apparel", "landscape_hardscape": "Landscape/Hardscape",
          "light_construction": "Light Construction", "septic": "Septic", "towing": "Towing", "other": "Other"}


# --- The thresholds (what each does and why: see the top of this file) ------------------------------------------
# 1. Website check
WRONG_SITE_THRESHOLD = 0.15         # website check under this: a "website issue" (the site doesn't show this


                                    # company), so not classified (unless CRM phone, ZIP or email domain is on it)
PARTIAL_BOT_CHECK_THRESHOLD = 0.75  # a bot check let the crawl read only the home page: the answer stands only at this


                                    # probability or more; under it, not classified, and the next crawl tries again
# 2. Segment
OTHER_THRESHOLD = 0.80       # Other bar: Other only when the model's probability for Other is this or more; under


                             # it the account gets its likeliest segment (a missed customer costs more than a call)
SAFETY_NET_THRESHOLD = 0.50  # safety net against Other: a segment whose main-business score is this or more gets


                             # that segment, never Other, however sure the model is of Other
# 3. Main business
MAIN_BUSINESS_THRESHOLD = 0.40  # main business Yes (core) when the segment's main-business score is this or more;


                                # under it No (non-core: the company does the work alongside another main business)
# 4. How sure (the colour of the Probability cell)
HIGH_BAND = 0.90    # High confidence (green) at this probability or more


MEDIUM_BAND = 0.75  # Medium confidence (yellow) at this or more; under it Low (red): a close call


# 5. Doubts (shown with an answer; they don't decide it)
UNSURE_SITE_THRESHOLD = 0.40  # website check under this, with no CRM details on the site: "may not be their site"


THIN_SITE_WORDS = 150         # fewer words of website text than this were sent: "little website text"


# 6. Review
REVIEW_THRESHOLD_DIFFERS = 0.50  # under this when the segment differs from the CRM/ZoomInfo label: Review sheet


REVIEW_THRESHOLD_MATCHES = 0.30  # under this when the segment matches the label: Review sheet (the model leaned


                                 # Other and a threshold kept the segment)

# Which rule decided the segment (choose()'s third value; shown in the rationale and the evidence log)
MODEL_PICK, OTHER_BAR, MAIN_NET, SURE_OTHER = "model's pick", "Other bar", "main-business safety net", "sure Other"


# --- 1. Website check ------------------------------------------------------------------------------------------
def wrong_site(site_match, crm_evidence, cleared_by_hand=False):
    """True when the site isn't the company's. CRM phone, ZIP or email domain on the site always passes it, and so
    does a site someone cleared by hand."""
    return site_match < WRONG_SITE_THRESHOLD and not crm_evidence and not cleared_by_hand


def partial_bot_check_unsure(crawl_reason, probability):
    """True when a bot check let the crawl read only the home page (crawl reason "partial_bot_check") and the model
    wasn't sure enough from it. A clear home page ("screen printing and embroidery since 1998") still gets its answer;
    an unclear one waits for the next crawl, which tries the site again, one page at a time."""
    return crawl_reason == "partial_bot_check" and probability < PARTIAL_BOT_CHECK_THRESHOLD


# --- 2. Segment ------------------------------------------------------------------------------------------------
def choose(model_pick, probabilities, main_scores, other_threshold=OTHER_THRESHOLD,
           safety_net_threshold=SAFETY_NET_THRESHOLD):
    """The segment rule, in one place: (segment, its probability, which rule decided it).

    The model's own pick stands, except that Other must pass two checks first:
      1. main-business safety net: if some segment's main-business score is safety_net_threshold or more, that segment
      2. Other bar: if the model's probability for Other is under other_threshold, the likeliest segment
    Only when both pass is the answer Other. The probability returned is always the chosen answer's own; when a
    check overrides Other it is low, so the account lands in the review queue."""
    if model_pick != "other":
        return model_pick, probabilities[model_pick], MODEL_PICK
    top_main = max(SEGMENTS, key=main_scores.get)
    if main_scores[top_main] >= safety_net_threshold:
        return top_main, probabilities[top_main], MAIN_NET
    if probabilities["other"] < other_threshold:
        likeliest = max(SEGMENTS, key=probabilities.get)
        return likeliest, probabilities[likeliest], OTHER_BAR
    return "other", probabilities["other"], SURE_OTHER


def segment(answers):
    """choose() on a fresh answer from the model."""
    industry = answers["industry"]
    probabilities = {o: industry["probabilities"].get(o, 0) for o in OPTIONS}
    main_scores = {s: answers[f"main_{s}"]["noul"] for s in SEGMENTS}
    return choose(industry["choice"], probabilities, main_scores)


def redecide(row, other_threshold=OTHER_THRESHOLD, safety_net_threshold=SAFETY_NET_THRESHOLD):
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
    return choose(model_pick, probabilities, main_scores, other_threshold, safety_net_threshold)


# --- 3. Main business ------------------------------------------------------------------------------------------
def main_business(answers, chosen):
    """main_<segment> for the chosen segment (0-1), None for Other."""
    return None if chosen == "other" else answers[f"main_{chosen}"]["noul"]


def main_yes(value):
    """'Yes' / 'No', '' for Other."""
    return "" if value is None or pd.isna(value) else "Yes" if value >= MAIN_BUSINESS_THRESHOLD else "No"


# --- 4. How sure, and why ----------------------------------------------------------------------------------------
def how_sure(probability):
    """'High', 'Medium' or 'Low' for the result's probability (Low = a close call)."""
    if probability >= HIGH_BAND:
        return "High"
    return "Medium" if probability >= MEDIUM_BAND else "Low"


def runner_up(row):
    """The likeliest option other than our answer, e.g. 'Other (36%)'. (When a threshold kept a segment, Other is
    the likeliest option of all, so the runner-up is Other, not the second on the list.)"""
    others = [o for o in OPTIONS if o != row["segment"]]
    second = max(others, key=lambda o: row[f"p_{o}"])
    return f"{LABELS[second]} ({row[f'p_{second}']:.0%})"


def rationale(row, other_threshold=OTHER_THRESHOLD):
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
        parts = [f"{label}: model leaned Other ({row['p_other']:.0%}, under the {other_threshold:.0%} bar)"]
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
    if crm and row["site_match"] < UNSURE_SITE_THRESHOLD:
        parts.append(f"Website confirmed by CRM {crm}")
    return ". ".join(parts)


# --- 5. Review -------------------------------------------------------------------------------------------------
def review_reasons(row):
    """What could be wrong with an answer, e.g. 'close call with Other (36%); little website text'. '' = none.
    Each reason, in order:
      close call                   probability under 75% (shown red); names the runner-up, e.g. "Other (36%)"
      another segment looks main   a segment other than ours has a main-business score of 40% or more
      website may not be theirs    website check under 40% and no CRM details on the site
      little website text          fewer than 150 words were sent to the model
    Disagreement with the input file's label is added by the report. These doubts are shown, not used to pick the
    Review sheet: that goes by probability (section 6 at the top of this file, report.split_for_checking)."""
    reasons = []
    if row["probability"] < MEDIUM_BAND:
        reasons.append(f"close call with {runner_up(row)}")
    other_main = [s for s in SEGMENTS if s != row["segment"] and row[f"main_{s}"] >= MAIN_BUSINESS_THRESHOLD]
    if other_main:
        top = max(other_main, key=lambda s: row[f"main_{s}"])
        reasons.append(f"{LABELS[top]} looks like its main business")
    evidence = row.get("crm_evidence")
    if row["site_match"] < UNSURE_SITE_THRESHOLD and not (isinstance(evidence, str) and evidence.strip()):
        reasons.append(f"website may not be the company's (site check {row['site_match']:.2f})")
    if row["words_sent"] < THIN_SITE_WORDS:
        reasons.append(f"little website text ({row['words_sent']} words)")
    return "; ".join(reasons)
