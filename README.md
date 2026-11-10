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
   plain download or are built with JavaScript.
2. **Phase 2, `phase2_classify.ipynb`.** Sends the most useful pages of each website to Decision-1 with our questions,
   applies our rules to the answer, and writes the report.

Both are safe to stop and re-run: finished accounts are on disk and skipped. A new set of accounts gets its own file
names (input, crawl store, answers, evidence log, report) in the notebooks' settings.

**Current sets:** `data/zoominfo_100each_2.xlsx` for Decision-1 (118 fresh accounts per segment label, about 100
classified each) and `data/compare_20each.xlsx` for the model comparison (24 per segment label). Neither overlaps any
earlier set.

## How an account is decided

1. **Is it their website?** Decision-1 compares the business name on the site with the CRM name. A clearly different
   site is not classified (it is listed for CRM clean-up). The CRM phone number, ZIP code or email domain on the site
   always confirms it.
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
6. **What to check.** Mostly only a difference from the CRM or ZoomInfo label can need correcting. Three sheets:
   - **Review:** we differ from the label AND our answer is unsure (a close call, another segment that looks like
     the main business, a doubtful website, very little website text); plus any segment under 50% even when it
     matches the label, since the model thought something else (usually Other) was at least as likely. The ones
     to check.
   - **Label differences:** we differ from the label and our answer is sure. Usually the label is wrong for our
     purposes (a home builder labelled Light Construction); skim them, above all the ones we call Other.
   - **Non-core:** companies that do a segment's work alongside a different main business, kept to count them.
   With no label to compare with, Review holds every unsure answer.

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
| **Phase 1: download the websites** | |
| `crawl.py` | which accounts need crawling, handing the work to the workers, the crawl store (reading and writing it), `make_sample()` for a new set |
| `crawl_worker.py` | the crawler itself: which links to follow, fetching a website's pages, deciding whether what came back is a real business site (or parked, dead, blocked); runs as several processes at once |
| `page_rules.py` | which pages are most useful (used by the crawler to pick links, and by Phase 2 to pick pages) |
| **Phase 2: classify** | |
| `questions.py` | every word Decision-1 is asked: the segment descriptions, who does the work, main business, website check |
| `classify.py` | what the model reads about each account, the run, the answers file and the evidence log |
| `model_api.py` | calling the models (Decision-1, Jev): endpoints, keys, pacing under the quota, retries |
| `decide.py` | every rule and threshold that turns the model's answer into a decision, and the rationale |
| `report.py` | the Excel report and the accounts CSV |
| **Model comparison** | |
| `compare.py`, `compare_models.ipynb` | the same accounts to Decision-1 and Jev, with identical input and the same rules, side by side |
| **Notes** | |
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
| A new kind of parked or dead site | `crawl_worker.py`, section 3 (patterns, each with examples) | applies from the next crawl |
| Add a model | `MODELS` in `model_api.py`, and its key in `.env` | use it in the comparison |
| A report column or sheet | `report.py` (and the Guide text in `report_guide()`) | rebuild the report |

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
