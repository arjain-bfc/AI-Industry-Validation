"""The report's words: its column names, and the sheets that explain it.

  what_the_model_answers()  the 7 questions, which numbers decide each result, worked examples
  how_it_decides()          the process step by step, with the thresholds in use
  report_guide()            what every column and sheet means
  thresholds_guide()        the thresholds in use, in a line each

The numbers in these texts are read from decide.py, so the report always describes the rules actually in use.
RULES.md says the same in a document.
"""
from decide import (HIGH_BAND, LABELS, MAIN_BUSINESS_THRESHOLD, MEDIUM_BAND, OTHER_THRESHOLD,
                    PARTIAL_BOT_CHECK_THRESHOLD, REVIEW_THRESHOLD_DIFFERS, REVIEW_THRESHOLD_MATCHES,
                    SAFETY_NET_THRESHOLD, WRONG_SITE_THRESHOLD)
import decide
from questions import SEGMENTS


CRM_URL = ("https://beaconfunding.crm.dynamics.com/main.aspx?appid=c993cfe6-9fc6-4dc2-8749-69c92c6c4b53&forceUCI=1"
           "&pagetype=entityrecord&etn=account&id={account_id}")


VERDICT, NOTES = "Verdict", "Notes"


OLD_VERDICT = "Your verdict"  # the column's name in reports built before 2026-11-10, still read back


ACCOUNT_LINK = "Account (website-link)"  # on the sheets people work through: the name, clickable


KEY = {label.lower(): option for option, label in decide.LABELS.items()}  # "septic" -> "septic", ...


AI_INDUSTRY = "AI predicted industry"  # the industry Decision-1 and our rules gave the account


def ai_probability_for(label_name):
    """The column with the AI's probability for the label's industry, e.g. 'AI probability for the CRM industry'."""
    return f"AI probability for the {label_name} industry"


def thresholds_guide(bars=None):
    """[(threshold, value and meaning)] for the Guide sheets. bars: a model's own Other bar / main-business net."""
    bars = {"other_threshold": decide.OTHER_THRESHOLD, "safety_net_threshold": decide.SAFETY_NET_THRESHOLD,
            **(bars or {})}
    high, medium = decide.HIGH_BAND, decide.MEDIUM_BAND
    return [
        ("Other bar", f"{bars['other_threshold']:.2f}: Other only when the model leans Other with at least "
                      "this probability"),
        ("Main-business safety net", f"{bars['safety_net_threshold']:.2f}: Other only when every segment's "
                                     "main-business score is below this; otherwise that segment"),
        ("Main business", f"{decide.MAIN_BUSINESS_THRESHOLD:.2f}: Yes at this main-business score or more, else No"),
        ("Probability colours", f"green = High ({high:.0%} or more), yellow = Medium ({medium:.0%} to {high:.0%}), "
                               f"red = Low (under {medium:.0%}: a close call, so it is in the review queue)"),
        ("Website check", f"below {decide.WRONG_SITE_THRESHOLD:.2f}: a website issue, the site doesn't show this "
                          "company (not classified), unless the CRM phone, ZIP or email domain is on it"),
        ("Partial bot check", f"{decide.PARTIAL_BOT_CHECK_THRESHOLD:.2f}: when a bot check let the crawl read only the "
                              "home page, the answer stands only at this probability or more; under it the account "
                              "is not classified and the next crawl tries again"),
    ]


def report_guide(label_name):
    """The Guide sheet of the Phase 2 report: what each column means, and the thresholds in use."""
    label = f"{label_name} industry" if label_name else "Label"
    return {
        "Accounts sheet (Output 1): one row for every account in the input file": [
            ("Account, Website", "the CRM account and the website that was read"),
            (label, f"the industry the input file gives ({label_name or 'none'}); never used to decide"),
            ("Result", "the AI predicted industry, from the industry question (one choice out of 6: our 5 segments "
                       "or Other), checked against the thresholds; 'not classified' when the account stopped before "
                       "a decision (see Stopped at and Problem)"),
            ("Probability", "the industry question's probability for the result (0-100%). Coloured green, yellow or "
                            "red by how sure (see Thresholds)"),
            ("Main business", "from a separate question, asked once for each of the 5 segments: is this segment's "
                              "work the company's main business? Shown for the chosen segment only. Yes: it is. No: "
                              "the company does the work alongside another main business. Blank for Other"),
            ("Match", f"the AI predicted industry is the same as the {label_name or 'label'} industry"),
            (ai_probability_for(label_name) if label_name else "AI probability...",
             "how much the model backs the label's industry (0-100%)"),
            ("Rationale", "one line: what decided it and the number behind it, main business, the pages naming the "
                          "work (e.g. 'Towing, 92% sure. Main business: no. Pages: /24-hour-towing')"),
            ("Doubts", "what could be wrong with the answer (a close call, another segment that looks like the main "
                       "business, a doubtful website, very little website text); blank = none. Shown to explain; "
                       "which sheet an account goes to depends on its probability"),
        ],
        "The sheets to work through": [
            (ACCOUNT_LINK, "the CRM account's name; click it to open the website that was read"),
            ("CRM", "click 'link' to go to the account in the CRM"),
            ("Review", f"segments the model itself found unlikely: under {decide.REVIEW_THRESHOLD_DIFFERS:.0%} when "
                       f"they differ from the input file's label, under {decide.REVIEW_THRESHOLD_MATCHES:.0%} when "
                       "they match it (the model leaned Other; the threshold kept the segment). The ones to check: "
                       "pick a verdict. An account you gave a verdict or note stays here even if a later run no "
                       "longer flags it"),
            ("Label differences", "every other difference from the label. Usually the label is wrong for our purposes "
                                  "(a home builder ZoomInfo calls Light Construction); skim them, above all the ones "
                                  "we call Other"),
            ("Accounts that match the label", "not listed anywhere to check (unless seriously unlikely, see Review): "
                                              "nothing would change in the CRM"),
            ("Non-core", "the company does a segment's work alongside a different main business (an auto shop that "
                         "also tows). Kept to count them over time; nothing to fix"),
            ("Not classified", "accounts that stopped before a decision, with the stage and the problem. Fix what can "
                               "be fixed (a wrong CRM website) and re-run; blocked or unresponsive sites are retried "
                               "on the next crawl"),
        ],
        "Not classified sheet (and the Accounts sheet's last columns)": [
            ("Stopped at", "the stage where it stopped: 1 crawl, 2 website text, 3 model call, 4 website check"),
            ("Problem", "why, in plain words (a dead or parked site, a site that refused us, a failed model call, "
                        "a website issue with what the page shows, not crawled yet)"),
            ("Crawl, Pages crawled", "how the crawl ended (status and reason) and how many pages it saved"),
        ],
        "Colours": [
            ("Headers", "blue: the answers; orange: how sure; green: main business; grey: explanations"),
            ("Cells", "Probability: green High, yellow Medium, red Low. Match green, Mismatch red"),
        ],
        "Thresholds in use (decide.py)": thresholds_guide(),
    }


# --- What the model answers, and which numbers decide what (the report's first sheet, RULES.md section 1) --------
def what_the_model_answers():
    """{title: (column names, [rows])}: the questions, which numbers decide each result, and worked examples (real
    numbers from the pilots, company names left out)."""
    return {
        "What Decision-1 is asked: 7 questions in one call per account": (
            ["#", "Question", "Answer", "Used for"],
            [("Q1", "Industry: which industry is this company most closely tied to, by the equipment it uses or would "
              "buy?", "one of Decorated Apparel / Landscape-Hardscape / Light Construction / Septic / Towing / Other, "
              "with a probability for each (the six add up to 100%)", "the AI predicted industry and its Probability"),
             *[(f"Q{n}", f"Is {LABELS[s]} work this company's main business?", "a 0-1 score, on its own",
                "Main business Yes/No for the chosen industry; the safety net against Other")
               for n, s in enumerate(SEGMENTS, start=2)],
             ("Q7", "Website check: is this website the company's own?", "a 0-1 score",
              f"a website issue under {WRONG_SITE_THRESHOLD:.0%}")]),
        "Which numbers decide what": (
            ["Result", "Numbers used", "Rule"],
            [("Website issue (not classified)", "website check", f"under {WRONG_SITE_THRESHOLD:.0%}, unless the CRM "
              "phone, ZIP or email domain is on the site"),
             ("AI predicted industry", "the 6 industry probabilities; for Other also the 5 main-business scores",
              f"the model's pick, except Other: Other needs {OTHER_THRESHOLD:.0%} or more AND every main-business "
              f"score under {SAFETY_NET_THRESHOLD:.0%}; otherwise the likeliest segment"),
             ("Probability", "the industry probability of the result", f"High {HIGH_BAND:.0%}+, Medium "
              f"{MEDIUM_BAND:.0%}-{HIGH_BAND:.0%}, Low under {MEDIUM_BAND:.0%}"),
             ("Main business (Yes / No)", "the main-business score of the chosen segment only",
              f"Yes at {MAIN_BUSINESS_THRESHOLD:.0%} or more; blank for Other"),
             ("Held back (partial bot check)", "the Probability, when a bot check let us read only the home page",
              f"kept at {PARTIAL_BOT_CHECK_THRESHOLD:.0%} or more; otherwise tried again on the next crawl"),
             ("Review sheet", "the Probability, and the CRM/ZoomInfo label", f"under {REVIEW_THRESHOLD_DIFFERS:.0%} "
              f"when it differs from the label, under {REVIEW_THRESHOLD_MATCHES:.0%} when it matches"),
             ("AI probability for the CRM/ZoomInfo industry", "the industry probability of the label's option",
              "shown only, never used to decide")]),
        "Worked examples (real numbers)": (
            ["Company", "Industry answer (6 options)", "Main-business answers (5 segments)", "Result"],
            [("An excavation contractor", "Light Construction 100%", "Light Construction 99%, others under 10%",
              "Light Construction, main business Yes (the model's pick)"),
             ("An auto body shop with its own tow truck", "Towing 97%", "Towing 13%",
              "Towing, main business No: it tows, but its main business is body repair (non-core)"),
             ("A collision shop with a towing page", "Other 70%, Towing 29%", "Towing 2%",
              f"Towing at 29%: Other is under {OTHER_THRESHOLD:.0%}, so the likeliest segment; sent to Review"),
             ("A print shop", "Other 92%, Decorated Apparel 8%", "Decorated Apparel 68%",
              f"Decorated Apparel: a main-business score of {SAFETY_NET_THRESHOLD:.0%} or more blocks Other "
              "(safety net)"),
             ("A roadside-assistance app", "Other 99%", "all under 2%", "Other: sure, and nothing looks like a main "
              "business")]),
    }


# --- The process in plain words (first sheet of the report) -----------------------------------------------------
def how_it_decides():
    """[(step, what happens)] for the report."""
    return [
        ("1. Read the website", "Phase 1 crawls the company's website, most informative pages first (a company's "
         "own Facebook or Instagram page counts; directory and review listings don't). Phase 2 sends the best pages "
         "(home, about, services, pages naming our segments) to Decision-1 with our questions. Accounts without a "
         "usable website are not classified; the Not classified sheet says where they stopped and why."),
        ("2. Is it their website?", f"Decision-1 checks that the site belongs to the company: the business name the "
         f"site shows, and a site that says what the business does. A different business, a listing, or a page with "
         f"nothing but a name (parked, coming soon) fails (score under {WRONG_SITE_THRESHOLD:.0%}): a website issue, "
         "shown with what the page says, and the account is not classified. The CRM phone number, ZIP code or email "
         "domain on the site always passes this check. When a bot check let the crawl read only the home page, the "
         "answer is kept only if Decision-1 is at least "
         f"{PARTIAL_BOT_CHECK_THRESHOLD:.0%} sure; otherwise the account waits for the next crawl."),
        ("3. Which segment?", "The industry question (one choice out of 6: our five segments or Other). A company "
         "gets one of our five segments when it does that segment's work itself, the "
         "kind of work done with equipment we finance (embroidery and print machines, landscape and light-construction "
         "equipment, septic and vacuum trucks, tow trucks). Work it only arranges, resells or hands to another company "
         "doesn't count, and neither does only selling or repairing the equipment. The label in the CRM or ZoomInfo "
         "is not used."),
        ("4. Other only when sure", f"Other means we would not finance equipment for this company. A missed customer "
         f"costs more than an extra call, so Other needs at least {OTHER_THRESHOLD:.0%} from Decision-1; "
         "anything less goes to the likeliest segment. And if a segment looks like the company's main business "
         f"({SAFETY_NET_THRESHOLD:.0%} or more), it gets that segment, never Other."),
        ("5. Main business", f"A separate question, asked once for each segment on its own. Shown for the chosen "
         f"segment. Yes: the segment's work is the company's main business, judged from the whole site "
         f"(headline, services, projects), not the headline alone. No: the company does the work, but alongside a "
         f"different main business (an auto repair shop that also tows). Yes at {MAIN_BUSINESS_THRESHOLD:.0%} or more. "
         "Blank for Other."),
        ("6. How sure, and rationale", f"The model's probability for the result. High: "
         f"{HIGH_BAND:.0%}+, Medium: {MEDIUM_BAND:.0%}-{HIGH_BAND:.0%}, "
         "Low: below that (a close call). Each account has a short rationale built from the same numbers: which rule "
         "decided it, main business, the pages naming the work, and how the website was confirmed."),
        ("7. What to check", "The thresholds already settle each answer, so a person checks only a segment the model "
         f"itself found unlikely: Review lists segments under {REVIEW_THRESHOLD_DIFFERS:.0%} that differ from the CRM "
         f"or ZoomInfo label, and segments under {REVIEW_THRESHOLD_MATCHES:.0%} that match it (the model leaned Other "
         "and the threshold kept the segment). Label differences lists every other difference from the label (a "
         "skim). Non-core lists companies that do a segment's work alongside a different main business. The Doubts "
         "column says what could be wrong with any answer. Verdicts and notes are kept when the report is rebuilt."),
    ]
