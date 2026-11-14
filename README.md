# Industry Validation Pipeline (Beacon Funding)

**What it's for.** Each CRM account gets the equipment segment Beacon could finance for it, read from the company's
own website. The CRM's Primary Industry drives outbound sales and marketing, so the goal is to reach companies that use
our equipment, even when their industry only looks close to ours.

| Segment | Equipment we finance |
|---|---|
| Decorated Apparel | embroidery machines, screen printing presses, DTG/DTF printers, sign and label equipment |
| Landscape/Hardscape | commercial mowers, chippers, stump grinders, compact tractors, landscape trucks |
| Light Construction | backhoes, excavators, skid steers, trenchers, loaders, hydrovac trucks, boom trucks |
| Septic | septic pumper, vacuum and jetter trucks, portable restroom trailers |
| Towing | tow trucks, wreckers, rollbacks, rotators, car carriers |
| Other | none of the above: we wouldn't finance equipment for this company |

## How it works

```
input Excel  ──Phase 1──>  crawl store  ──Phase 2──>  answers + evidence log  ──>  report + accounts CSV
(the accounts)  download     (every page of           ask Decision-1,             Output 1: industry, how sure,
                each website   each website)           apply our rules             rationale, review queue
                                                                                   Output 2: every stage, per account
```

1. **Phase 1, `phase1_crawl.ipynb`.** Downloads each account's website: the home page first, then its most useful
   pages (about, services, pages naming our trades), up to 40 pages. A real browser is used for sites that refuse a
   plain download or are built with JavaScript. Each web address is crawled once, however many accounts have it.
   CRM links to social media, directory, review and marketplace pages are not crawled; a company's own Facebook or
   Instagram page is, but only the page itself, its About page and its own posts. The same holds when a company's
   website sends visitors on to Facebook or Instagram: Facebook's own pages (log-in, help, policies) are never read.
2. **Phase 2, `phase2_classify.ipynb`.** Sends the most useful pages of each website to Decision-1 with our questions,
   applies our rules to the answer, and writes the report. The same company entered more than once (same website,
   same name) gets one call, and every record of it gets that answer.

Both are safe to stop and re-run: finished accounts are on disk and skipped. Phase 1 retries by itself: sites that
refused us or didn't answer are tried again after a wait (`RETRY_WAIT_MIN`, 1 min), up to 3 tries in a run, and
again on every later run: they are never given up on. Only dead and parked sites are dropped for good.

Both notebooks start with one line, `SET = "zoominfo_pilot"` (or another set): `datasets.py` lists the sets, and every
file of a set (crawl store, answers, evidence log, report) is named after its input file. A new set is one line there.

**Where the accounts come from:** the data warehouse, read directly (read only, your Windows login) with the two
queries in `queries/` (ZoomInfo accounts with no LCW opportunity; CRM accounts). `data_warehouse.py` saves each read as a
snapshot in `data/snapshots/`, and new sets are picked from the latest snapshot; `REFRESH = True` in the Phase 1
notebook reads the warehouse again. Within a label, a set takes a random pick of the accounts created in the last
month, or the newest ones when a label has too few.

**Current sets:** pilots first, `zoominfo_pilot` (`data/zoominfo_30each.xlsx`: 38 per segment, aiming at 30 usable)
and `crm_pilot` (30 per label, Other included); then the big runs `zoominfo_3` (100 usable per segment) and `crm_100`
(100 per label), made after the pilots so they skip the pilots' accounts. Earlier: `zoominfo_2`
(118 per segment), `crm_20` (20 per label) and, for the model comparison, `data/compare_20each.xlsx`. No two overlap.

## How an account is decided

**What the model answers.** One call per account, with the company's details and its best website pages, asks 7
questions and gets 12 probabilities back:

| Question | Kind | Answer |
|---|---|---|
| Website check | yes/no | 1 probability |
| Industry | one choice out of 6 (the 5 segments or Other) | 6 probabilities adding up to 100% |
| Main business, once per segment | yes/no, x5 | 5 probabilities, each on its own |

The industry question and the main-business questions are separate; the rules below combine them. RULES.md section 1
has a sample answer, which numbers decide each report column, and worked examples.

1. **Is it their website?** Decision-1 compares the business name the site itself shows with the CRM name, and checks
   that the site says what the business does. A different business, a listing on someone else's site, or a page with
   nothing but a name (parked, placeholder, "coming soon") is not classified: it is a "website issue", shown with
   what the page says, and is checked again only when the CRM web address changes (or in an occasional sweep,
   `RECHECK_WEBSITE_ISSUES` in Phase 1). A
   company's own Facebook or Instagram page counts as its website. The CRM phone number, ZIP code or email domain on
   the site always confirms it.
2. **Which segment?** A company gets a segment when it does that segment's work itself: the work our equipment is used
   for. When several segments fit, the one whose equipment most of its work needs. Work it only arranges, resells or
   hands to another company doesn't count, and neither does only designing, selling or repairing the equipment. When
   the site doesn't say who does the work, the company gets the benefit of the doubt.
3. **Other only when sure.** Losing a real business to Other costs more than a wasted sales call, so Other needs two
   things: Decision-1 is at least 80% sure it's Other, AND no segment looks like its main business (every main-business
   score under 50%). Otherwise it gets the likeliest segment.
4. **Main business, Yes or No.** Yes when the segment's work is the company's main business; No when it does the work
   alongside a different main business (an auto repair shop that also tows: Towing, main business No).
5. **How sure.** The model's probability for the result is coloured: green High (90% or more), yellow Medium
   (75-90%), red Low (under 75%, a close call). Each account also gets a short rationale built from the same numbers.
6. **What to check.** The thresholds already settle each answer, so a person only checks a segment the model
   itself found unlikely. Three sheets:
   - **Review:** a segment under 50% that differs from the CRM or ZoomInfo label, or under 30% that matches it (the
     model leaned Other and the threshold kept the segment). The ones to check.
   - **Label differences:** every other difference from the label. Usually the label is wrong for our purposes (a
     home builder labelled Light Construction); skim them, above all the ones we call Other.
   - **Non-core:** companies that do a segment's work alongside a different main business, kept to count them.
   With no label to compare with, Review holds the segments under 50%. The **Doubts** column says what could be
   wrong with any answer (a close call, a doubtful website, very little website text).

## The outputs

- **Output 1, the evaluation dataset:** the report's Accounts sheet (also saved as `report_..._accounts.csv`), with one
  row for **every account in the input file**. A classified account shows the result, its probability, main business, the
  CRM or ZoomInfo industry, Match/Mismatch, our probability for the label's industry and a one-line rationale
  ("Towing, 92% sure. Main business: no. Pages: /24-hour-towing"). An account that wasn't classified shows the stage it
  stopped at (1 crawl, 2 website text, 3 model call, 4 website check) and why. The Guide sheet explains every column,
  colour and threshold.
- **Output 2, the evidence log** (`evidence_....jsonl`, one line per account): the crawl, the website text sent to the
  model (pages, words, estimated tokens, phrases naming our trades), the website check, the decision (scores, the rule
  that decided it, the rationale) and the full input sent to the model. An account that stopped says at which stage
  (1 crawl, 2 website text, 3 model call, 4 website check, 5 decision) and why.

## The files

Each file has one job and starts with a plain explanation of it. Patterns and other hard-to-read logic are
broken down in comments with examples (a key to reading the patterns is at the top of each section that uses them).

| File | Job |
|---|---|
| **The accounts** | |
| `data_warehouse.py`, `queries/` | reading the accounts from the data warehouse (read only), saved as snapshots |
| `datasets.py` | the account sets (ZoomInfo, CRM): how each is picked, its input file and label; all its other file names follow |
| `accounts.py` | reading an input file: one tidy row per account and its CRM contact details; how two records are told to be the same company; which links aren't a company website (listings, social media) |
| **Phase 1: download the websites** | |
| `crawl.py` | the run: which accounts need crawling, handing the work to the workers, retries, saving each account; and the crawl store (one line per account with its pages, read by Phase 2) |
| `crawl_worker.py` | the crawler itself: which links to follow (narrowly on Facebook/Instagram), fetching a website's pages, each pass's verdict; runs as several processes at once |
| `site_checks.py` | is it a real business website (or parked, a placeholder, a bot check), and why a fetch failed |
| `page_rules.py` | which pages are most useful (used by the crawler to pick links, and by Phase 2 to pick pages) |
| **Phase 2: classify** | |
| `classify.py` | what the model reads about an account (its details and best pages within the token budget), and the run: which accounts need an answer, one call per company, saving each result |
| `questions.py` | every word Decision-1 is asked: the segment definitions, who does the work, main business, website check (and the questions version) |
| `model_api.py` | calling the models (Decision-1, Jev): endpoints, keys, the token budget, pacing under the quota, retries |
| `decide.py` | every rule and threshold that turns the model's 12 numbers into a decision, and the rationale |
| `results.py` | what Phase 2 writes: the answers file (one line per call) and the evidence log (how far each account got, and why it stopped) |
| **The report** | |
| `report.py` | what goes on each sheet (the accounts, what needs checking, the summary) and writing the workbook |
| `report_guide.py` | the report's words: column names, the questions and thresholds explained, the Guide |
| **Tools** | |
| `run_sets.py` | runs Phase 1 and Phase 2 for whole sets in one command, unattended, with a log in `data/run_logs/` |
| `check_set.py` | the check set: known accounts with agreed answers (Clear, Decided, Unclear cases), run after any rule change to see nothing broke |
| `compare.py`, `compare_models.ipynb` | the same accounts to Decision-1 and Jev, with identical input and the same rules, side by side |
| **Notes** | |
| `RULES.md` | every rule the model is given, in plain English, plus the questions and how the answers become a decision |
| `build_rules_doc.py` | builds the dated rules Word document from RULES.md: run it after editing RULES.md |
| `DECISIONS.md` | why each rule is what it is, newest first |

| Folder | What's in it |
|---|---|
| `data/` | input Excels, crawl stores, answers, evidence logs, reports |
| `old_versions/` | earlier code (`code_backups/`), old results, retired tools |
| `_crawl_jobs/` | the crawl workers' job files and logs while a crawl runs (a worker's log shows why it failed) |

## How to change things

| To change... | Edit | Then |
|---|---|---|
| A threshold (Other bar, main-business safety net, probability colours, website check) | the top of `decide.py` | rebuild the report: no new calls needed |
| What the model is asked | `questions.py` | test on known accounts first; give the answers file a new name |
| Add a segment | `questions.py` (a new entry in `DEFINITIONS`, with its main-business examples), `decide.py` (`LABELS`), `page_rules.py` (`SEGMENT_WORDS`, `SEGMENT_PHRASES`) | a new answers file |
| Which pages are fetched first | `page_rules.py` (word lists at the top) | applies from the next crawl |
| Page limits, time limits, number of workers | `CRAWL` and `PASSES` at the top of `crawl.py` | applies from the next crawl |
| A new kind of parked or dead site | `site_checks.py` (patterns, each with examples) | applies from the next crawl |
| Add a model | `MODELS` in `model_api.py`, and its key in `.env` | use it in the comparison |
| A report column or sheet | `report.py` (and the Guide text in `report_guide.py`) | rebuild the report |

Write down the reason for any rule change in `DECISIONS.md`.

## API keys and endpoint

The keys and Decision-1's endpoint live in `.env` in the project folder (read by `model_api.py`; `.gitignore` keeps it
out of git). Copy `.env.example` to `.env` and fill it in (ask the team for the values):

```
DECISION1_API_KEY=<the key>
DECISION1_URL=<Decision-1's Azure address>
JEV_API_KEY=<the key>
```

Keep `.env` private: never share or commit it. A variable already set in the environment (on a server, say) wins over
`.env`. Only the model comparison needs `JEV_API_KEY`.

## First time on a new machine

```
pip install -U crawl4ai pandas openpyxl requests model2vec python-dotenv
crawl4ai-setup
```
