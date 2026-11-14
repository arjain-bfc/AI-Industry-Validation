# Why the rules are what they are

The code says what happens; this file says why. Newest first.

## 2026-11-13
- **Code regrouped by job, nothing else changed.** Pieces had collected in the wrong files (the crawl store and the
  account reading inside crawl.py, the answers file and evidence log inside classify.py, report texts inside
  decide.py). Each job now has one home, in pipeline order: accounts (data_warehouse, datasets, accounts) -> crawl
  (crawl with the crawl store, crawl_worker, site_checks, page_rules) -> classify (classify with what the model
  reads, questions, model_api, decide, results) -> report (report_guide). A first split into 23 files was folded
  back to 18: more files than that made
  the folder harder to read than the code. Functions kept their code; classify.run and report.build were split into
  named steps. Checked with 42 fingerprints of everything computed without a model call (model input, decisions,
  report sheets, crawl decisions): identical before and after; plus live crawls and live calls.
- **Equipment lists checked against everything Beacon has financed or quoted** (all of dim.Asset, by type, make and
  model; read-only). Towing, Septic and the core Light Construction and Landscape machines were already covered
  (including the tow bodies filed under "Unknown"). Two general additions: Decorated Apparel now names "the
  equipment that supports the decorating work, such as drying, screen-making and finishing equipment" (thousands of
  dryers, exposure and washout units, pretreaters and folders), and Landscape/Hardscape names bucket trucks (tree
  work; mostly Altec and Versalift bodies). Boom trucks were already Light Construction. Left out on purpose, to keep
  the lists general: large cranes (a handful of records; "small cranes" stays), aerial lifts, directional drills,
  heavy-haul trailers, tree trimmers, utility tractors, digitizing software. Questions version 6ae5cacc -> 5c9c6e05.
- **Septic installation is said once (the Light Construction / Septic overlap rule), not five times.** It was in LC's
  work list, LC's includes, the overlap rule, LC's main-business examples and Septic's "installer that doesn't pump",
  and every one is read in both kinds of question. That made it override a company whose whole business is septic
  systems (one that installs, inspects and maintains aerobic systems scored LC 71-74% on 9 asks; the crawl was
  complete). Kept only the overlap rule. Tested on 16 septic and mixed accounts: that company Septic 3/3; six septic
  installers and servicers move to Septic; three excavation-led companies stay LC (a pump-and-dig company at LC 50%);
  a home inspector stays Other. Checked on 31 non-septic accounts (LC, builders, LH/LC mixes, hydrovac and vacuum
  firms): 30 unchanged, a brush, stump and tree company LC 53% -> LH 59% (better). In effect septic-system businesses are now Septic and excavation contractors that also
  install septic stay LC (open question 1, option B). Rewording the servicing side alone did not move the aerobic-systems company.
  Questions version c48ba6b0 -> 6ae5cacc.
- **The two kinds of question are now spelled out everywhere** (from the manager's review): the report, RULES.md,
  README and the code did not make clear that the industry is one question choosing 1 of 6 options (probabilities
  adding up to 1) and main business is 5 separate yes/no questions, one per segment. RULES.md section 1, the report's
  first sheet ("How it decides"), the Guide, README, questions.py and decide.py now show the input, the 7 questions
  and 12 numbers, a sample answer, which numbers decide each report column, and worked examples (one table in
  decide.what_the_model_answers(), shared by the report). No change to the questions or the decisions.
- **"When several segments fit" counts services, not repetition.** "The equipment most of the company's work needs"
  was being judged by how much of the site talks about each kind of work, so a company with many service-area pages
  about one service leaned that way. A portable toilet, septic service and excavation company (its area pages
  repeat excavation) was a coin flip between Septic and Light Construction. Added "counting the services it offers,
  not how often the site repeats them". Tested on 24 accounts where two segments fit (13 Septic/LC, 11 Landscape/LC),
  old and new wording: that company Septic 3/3 (was LC, SE, LC); a sewer service (septic and drain cleaning, pumping,
  installs, sewer repair) Septic 3/3 (was LC 3/3 at 50-53%); the other 22 kept their segment, apart from two 50/50
  tree-and-excavation companies that wobbled either way under both wordings. Pump-and-dig companies whose services are
  mostly digging (six of them) stay LC, as in open
  question 1; landscapers whose whole site is landscaping held or firmed up (one drainage company 62% -> 80% LH). Questions
  version fb4db254 -> c48ba6b0.
- **A failed website check is a "website issue", not "fix the CRM URL".** Of the 60 accounts that failed the check
  so far, many were not wrong CRM addresses: domains taken over by gambling spam, companies bought out (a sewer and
  drain company's site now shows a national franchise), domains for sale, error pages ("500 Internal Server Error", two "Index of /" pages,
  from 36 to 1,051 words), placeholders. The check caught them all, so no new patterns were added to Phase 1 (each
  run turned up a new kind); instead the label says "website issue" and shows the page's own title, which says what
  the issue is. A word limit to tell error pages from other businesses was rejected: error pages ran from 36 to 1,051
  words. Placeholder pages over 60 words were left to the website check too (raising the 60-word placeholder rule
  would hold back small builders whose sites say "homes under construction").
- **Website issues are not tried again on their own.** About 2% of accounts fail the check; at 100,000 accounts that
  is 2,000-3,000 re-crawls and model calls per run, mostly for sites that won't change. They are checked again when
  the CRM web address changes, or in an occasional sweep (RECHECK_WEBSITE_ISSUES in Phase 1, off by default).
- **Facebook and Instagram are never crawled like an ordinary website.** One builder's domain sends visitors to Facebook,
  which showed its log-in page; the crawler then read Facebook's help, policies and sign-up pages as the builder's site.
  Wherever a crawl lands on Facebook or Instagram it now follows the company-page rules: a log-in page is "blocked"
  (tried again next run), no company page at all is "dead_site", and Facebook's own pages are never read.
- **A vacuum truck is judged by its use (the overlap rule, and who counts as Septic).** Hydrovac rigs are financed as
  excavation equipment, so hydro excavation is Light Construction (2026-11-06), but the same kind of
  truck also does industrial vacuum work (tank cleaning, spill clean-up), which is Septic. The definitions now say so:
  digging with the truck is Light Construction, vacuuming and hauling liquids, sludge or waste is Septic, and a
  company doing both goes to the one it mainly presents. Tested on 9 accounts with the old and new wording: a hydro
  excavation company stayed Light Construction (96%), 7 industrial vacuum and environmental companies that also offer hydro
  excavation stayed Septic (96-100%, no score moved more than 0.06), and an industrial maintenance company (home page
  only) moved from Other-leaning (Septic 26%) to Septic 59%, still held back as a partial bot check. Questions version
  79ea4759 -> e401da62. Narrowed the same day (fb4db254): the first wording listed "septic, sewer and drain work" as
  septic and added "a company that does both is judged by which it mainly presents". Asked 3 times each, a sewer
  and septic company (installs and repairs, doesn't pump: LC under Septic's "main business: no" examples) went Septic 3/3,
  and the portable toilet, septic and excavation company went LC 3/3. Now only pumping and hauling with the
  truck is septic, and the "does both" clause is gone (the general rule, the equipment most of the work needs, covers
  mixed companies): the sewer and septic company back to LC 3/3, the portable toilet company a 50/50 toss-up as before (an edge case), the hydro excavation company LC 97%, the 7
  vacuum companies Septic 96-100%.
- **"Side line" is now "non-core work" everywhere the model reads it** (the Light Construction definition and two
  places in the general rules), the term used across the project. Tested on 8 non-core accounts from the ZoomInfo
  pilot with the wording before and after: all kept their segment and main business No; probabilities moved by 0.06
  or less except one (Landscape/Hardscape 0.72 -> 0.86). Questions version e401da62 ->
  2ca4cf09.
- **A bot-checked site keeps its answer only when the home page settles it (0.75).** When a bot check lets the crawl
  read only the home page, the model is still asked, but its answer counts only at a probability of 0.75 or more;
  under that the account is not classified ("partial_bot_check_unsure") and waits for the next, gentle crawl. A clear
  home page
  is enough (a screen printer: Decorated Apparel 99.9%, crawled behind Cloudflare); an unclear one isn't
  (an industrial maintenance company: 218 words of an environmental-services home page, 26% for Light Construction, then
  27% for Septic on a second call). Blocking every bot-checked site was rejected: a site that always blocks would
  never get an answer. Asking the model whether it had enough information was rejected too: models judge that
  poorly, and a new question would change the questions version; the probability already says it. The model is not
  told that pages were blocked: the gate is in code, where it is predictable.

## 2026-11-12
- **Sites behind a bot check: stop early, label it, try gently next time.** Some sites (about 3% of the ZoomInfo
  pilot) let the home page through but refuse every other page with a Cloudflare check; they were labelled "thin",
  as if the site had little on it. Now the first inner page refused by a bot check ends that site's crawl (keeping
  the home page and anything already fetched), the site is labelled "partial_bot_check", and the next run crawls it
  again gently: one page at a time, 8 seconds apart. A retry of refused pages at the time was tried and dropped: on
  one screen printer it took 407 seconds instead of 126 and got nothing more, and the gentle crawl didn't
  get through either (pacing alone isn't enough there); getting past a bot check by any other means is not done.
  Also: when an account is crawled again, Phase 2 now asks the model again (the crawl is newer than its answer), and
  a crawl due for another try is never copied to another account (it was copying itself, so the re-crawl never ran).
- **Report wording: "AI predicted industry"** (was "Our industry") and "AI probability for the CRM industry" (was
  "Our probability for..."), the AI's probability for the label's own industry. "Probability" stays for the AI's
  own answer: "Confidence" is a field of its own in both models.
- **Accounts are read from the data warehouse, not Excel exports.** The two export queries (ZoomInfo accounts with
  no LCW opportunity; CRM accounts, opportunities included on purpose) live in `queries/` and run read-only with a
  Windows login (`data_warehouse.py`). Each read is saved as a snapshot in `data/snapshots/` and every step works from the
  latest one; `REFRESH` reads the warehouse again. Compared with the exports: the same accounts plus those added
  since (769 ZoomInfo, 663 CRM), minus those gone inactive, and none of the Excel artefacts (`_x000D_`, "NULL").
- **New sets take recent accounts.** Accounts under 6 months old crawled better (90% usable, against 86% at 6-12
  months and 62-83% for older ones, on 2,037 crawled accounts). But "the newest" per label was sometimes one bulk
  import (all 125 newest ZoomInfo Light Construction accounts from one day), so within a label a set takes a random
  pick of the accounts created in the last month, or the newest when a label has fewer (most CRM labels, and ZoomInfo
  Decorated Apparel, Septic and Towing). PAD went from 20% to 25%. Pilots first (ZoomInfo 30 usable per segment,
  CRM 30 per label) to run today's changes end to end on fresh accounts, then `zoominfo_3` and `crm_100` (100 usable
  per label), picked after the pilots so no account is tested twice.
- **Blocked and unreachable sites are never given up on.** They used to get 3 tries in all and then stay "not
  classified" for good. Being refused (bot protection, a Facebook log-in wall) or not answering is usually
  temporary: Facebook's log-in walls, for one, lasted hours to a day after repeated visits. Now every Phase 1 run
  tries them again; the 3-try limit (with the 1-minute wait) applies within one run. Dead sites that may come back
  are tried again on every run too: a placeholder ("coming soon", a suspended store), a home page giving a 404, a
  deleted Facebook/Instagram page. Dropped for good: a domain that doesn't exist, one a host says isn't set up
  anywhere, and parked or for-sale domains. Whatever the result, an account whose CRM web address has changed is
  crawled again (the crawl store already records which address got which result, so no separate list is kept), as
  is a link once skipped as social media that the skip list no longer covers (Facebook/Instagram pages from before
  2026-11-12). Also fixed: an account first stored with no website was never picked up after a URL was added.
- **Link tooltips are kept.** A link's title attribute isn't page text, and on an image button it can be the only
  words there are: one recovery company's booking buttons say "Repossession Scheduling" only in their
  tooltip, and nowhere else on its one-page site. The crawler now keeps tooltips that add something (not a repeat of
  the link's own text, not one word, not generic like "Home" or "Follow on Facebook"), and Phase 2 sends each once
  per site, like image labels. Tested on 5 crawled sites: 2 repossession companies gained "Repossession Scheduling",
  2 sites had none, 1 only social-media buttons (now filtered). It didn't change that company's answer (Towing 0.59, main
  business 0.38): its page is all lot rules and releases, so the model still hedges. Kept because it costs almost
  nothing; only new crawls have tooltips.
- **Main business weighs the headline with the rest of the site.** The main-business question and the LC
  build-or-remodel rule both let the name and headline decide. A builder (headline "Custom Home Builder &
  General Contractor"; site mostly renovations, additions and structural repair; About page "a general contracting
  company") scored 0.06-0.09 for LC as its main business. Now both weigh the headline together with the services
  listed, the projects shown and the rest of the site; neither the headline alone nor one page decides, and a company
  whose work is mainly renovating is LC even if its headline says builder. Letting the services override the
  headline was tried first and dropped: it pushed a general printer (business cards, banners) to "mainly Decorated
  Apparel" (0.71-0.73). Tested on 25 borderline accounts (5 per segment): that builder 0.85 and another remodeler 0.89
  (both from under 0.40); a repair shop that also tows fell to 0.27 (correctly No); the printer 0.47; most others
  moved within run-to-run noise (repeat runs of the same wording move borderline scores by 0.1-0.15, so flips near
  0.40 mean little). The 7 home builders and heavy contractors from the 2026-11-11 test all stay Other (0.95-0.99).
  Questions version 5f4b6ac4 -> 79ea4759.
- **The website check's name rule now needs the name ON the site, and a site that says what the business does.**
  The check said both "the site's name is the CRM name: rate it near 1" and "a placeholder page fails"; on a
  "coming soon" page showing only the name, the name won (a tree service, 0.68). Two general changes: the
  placeholder rule ends "even when it shows the company's name: a page that says nothing about what the business
  does is not a business site", and the name rule now reads "when the business name the site itself shows (in its
  title, headline, logo text or page text, not only in its web address) is the CRM name and the site shows what the
  business does, rate it near 1". A version naming the "coming soon" case was dropped as too specific. Tested on 33
  calls in all: the tree service now fails (0.11); sites that never name the CRM company fail cleanly instead of scoring
  0.15-0.56 run to run (a plumber's lead site, a tree care company on another tree service's domain, a clothing brand on the URL the CRM
  gives its parent company); under-construction sites
  that still say what they do, thin real sites (50-100 words), sites titled by initials or a slogan, and DBA sites
  all keep passing. In-between scores move by up to 0.3 between runs with no wording change, so single cases near the
  bar prove little. A code-level fix (counting words with repeated lines collapsed) was tried first and dropped.
  Questions version a551f436 -> 5f4b6ac4.
- **A company's own Facebook or Instagram page is now read, narrowly.** They used to be skipped as "social media";
  no reason was recorded, most likely the old belief that Facebook needs a log-in. Logged out, a business page still
  shows its intro, category and contact details (Facebook) or bio and post captions (Instagram), often enough to
  classify. Tested on 26 CRM accounts that have no other website: about 2 in 3 Facebook pages had a usable intro or
  category, and every Instagram profile had a bio. But crawled like a website, the crawler wandered into Meta's own
  pages and other businesses' pages (one account picked up another company's intro), so Phase 1 now fetches only
  the page itself, its About page and its own posts, and strips menus and log-in prompts. A log-in wall counts as
  blocked (retried on later runs); a deleted or friends-only page counts as dead. Other social, directory and
  marketplace sites gave nothing about the company (sign-up walls, their own menus; Etsy blocks crawlers with a
  captcha) and stay skipped. Facebook sends repeat visitors to its log-in page after a few dozen visits in a short
  time; a normal run visits each page once, so no extra slowdown was added. Meta's terms restrict automated
  collection: low risk at this volume, but a business call. About 350 CRM accounts have only a Facebook page. End-to-
  end test (2026-11-12): of 26 test accounts crawled, 14 came through (11 Facebook, 3 Instagram; the rest were log-in
  walls on a day Facebook was still throttling our repeat tests); all 14 passed the website check (0.50-1.00) and all
  14 matched the CRM industry, 12 of them at 0.96 or more. The two low ones had only a bare category ("Construction
  Company", an advertising agency doing apparel design). Facebook post pages give a logged-out visitor only the date,
  no caption; post text comes through when it shows on the page itself (the newest one or two).
- **The website check covers social media and listing pages.** The model's question now says a company's own
  Facebook or Instagram business page counts as its website, and another business's social page, a personal profile
  or a directory, review, marketplace or lead-generation listing doesn't. Tested on 20 calls: 7 Facebook/Instagram
  pages all passed (0.96-1.00); 4 directory listings all scored under 0.03; 9 ordinary sites kept their pass/fail
  (6 passed, 3 wrong websites failed). Known gap, accepted: CRM details on a page (phone, ZIP) pass the check
  whatever the model says, and a listing usually shows them (3 of the 4 would pass). Listing links in the CRM are
  skipped in Phase 1, so this only matters for a company domain that forwards to a listing, which is rare; a
  code-level stop for it was tried and dropped as not worth the extra rule. Directory listings are not followed to the
  company's own website either: classifying from listing text would need rules per directory, for about 15 accounts.
  Questions version 1bee83ce -> a551f436.

## 2026-11-11
- **The same company is asked once.** About 16% of CRM accounts share a web address with another account. Most are
  the same company entered more than once, but some are different businesses on one site (dealers on autovalue.com
  or uhaul.com, branches of a chain, a site that changed hands), so an answer can't be copied by website alone: the
  website check depends on the name. Now: each web address is crawled once (compared loosely: www, case and a
  trailing slash ignored), and accounts with the same address AND the same name and DBA (ignoring case, punctuation
  and legal endings like Inc or LLC) share one model call; the others still get their own. Anything less than an
  identical name gets its own call, because a wrong match would silently copy one company's answer to another,
  while a missed one costs only a call. Fuzzy name matching was tried and rejected: meaning-based similarity
  (model2vec) scored "Mike's Towing" vs "Mark's Towing" (different) above "Guy's Tree Care" vs "Guy's Tree Svc"
  (same), and exact matching already gets 95% of the possible saving. On the full CRM export: about 10% fewer
  crawls and 4% fewer calls; ZoomInfo has almost no duplicates. Copies say whose answer they share (`same_as`).
  Test sets pick each company once.
- **More sites count as "only a social media or listing page"** (not crawled): YouTube, TikTok, Pinterest, Nextdoor,
  Linktree, Google log-in/Maps links, directories (BBB, Yellow Pages, Manta, Angi, HomeAdvisor, Houzz, Trady...)
  and marketplaces (Etsy, Amazon, eBay), as found in the CRM export. Website builders (Wix, Weebly, GoDaddy Sites,
  Google Sites, Square) are the company's own site and are still crawled.
- **Light Construction's main-work rule now applies only to construction contractors.** The rule was meant to keep
  builders and heavy contractors that do some renovation out of LC, but its wording ("LC must be the company's main
  work") also stopped every other trade's side LC work from counting, unlike all other segments. Now: home builders,
  developers, commercial/industrial/multifamily GCs, structural or commercial concrete and civil/heavy contractors need
  LC as their main work; any other business doing LC work itself counts, even as a side line; rebuilds and ADUs built
  by a home builder are still home building. Tested on 14 crawled accounts (3 wordings, 40 calls) plus 6 current LC
  accounts: all 7 builders/heavy stay Other (v1 let a commercial concrete GC in, v2 a home builder doing fire
  rebuilds and ADUs); other trades now count with conviction (a pool builder 0.43 -> 0.85, a restoration/roofing firm
  Other -> LC 0.70); 5 of 6 LC accounts held, the 6th (a residential and commercial builder) became Other, consistent
  with the builder rule. Questions version a6131204 -> 1bee83ce: answers from earlier runs used the old wording.

## 2026-11-10
- **Crawl retries in the same run.** Sites that refused us or didn't answer used to need 2-3 manual re-runs;
  a second try rescued about 1 in 4 (8 of ~33 on the 500 set). `crawl.run` now waits `RETRY_WAIT_MIN` (1 min) and
  crawls only those again, until each has had `MAX_ATTEMPTS` (3) tries, so an automated run needs no babysitting. The
  23-37 min gap seen on earlier recoveries was only the time between manual re-runs, so the wait is kept short.
  `retry_wait_min=None` turns the wait off (they're left for the next run, as before).
- **Review goes by probability only (replaces the two rules below).** The thresholds are what make the answers
  robust, so a person checks only a segment the model itself found unlikely: under 0.50 when it differs from the
  label (`REVIEW_THRESHOLD_DIFFERS`), under 0.30 when it matches it (`REVIEW_THRESHOLD_MATCHES`; under 0.30 every
  such account on the 590 run was one the model leaned Other on, e.g. a real estate firm and a subcontractor
  network; 0.25 missed an architecture firm). Doubts (a close call, another segment that looks main, a doubtful
  website, little text) no longer pick the sheet; they are shown in a "Doubts" column (was "Why review") on every
  sheet. 590 run: Review 41 -> 15 (3 differ, 12 match), Label differences 137 -> 149.
- **Unlikely segments are checked even when they match the label.** On the 590-account run, 45 of 52 Low answers
  matched ZoomInfo and so were never checked. 22 of them were segments kept only by the Other bar (the model leaned
  Other at 0.53-0.80), e.g. a real estate firm, a towing consultant and a subcontractor network labelled Light
  Construction or Towing; ZoomInfo agreeing proves nothing there. Any segment under 0.50
  (`CHECK_EVEN_IF_MATCH_BELOW`) now goes to Review: every Other-bar keep is under 0.50 by definition (Other was the
  model's likeliest option), plus a few coin-flips. 0.40 was rejected: it missed 4 of the Other-bar keeps and has no
  clear meaning. Review on that run: 15 -> 41. Matching answers from 0.50 to 0.75 (mostly auto shops that tow, lawn
  companies) still aren't checked.
- **Probability instead of confidence.** The model's confidence field is its probability rescaled so a blind guess
  counts as 0: (p - 1/6) / (1 - 1/6) (checked on 1,000+ saved answers). When a threshold overrides Other the model
  gives no confidence for the segment we keep, so the column mixed two measures. Every decision rule already works on
  probabilities, so the report now shows the result's probability everywhere ("Probability" column; `how_sure`).
  The colour lines moved to the same scale: 0.70 confidence = 0.75 probability, 0.85 = 0.875, rounded up to 0.90.
  On the last run: same segment and rule for all 504 answers; Low unchanged (55); 18 High became Medium.
  Also fixed: a close call named the chosen segment as its own runner-up when a threshold had kept it ("close call
  with Towing" on a Towing account); the runner-up is now the likeliest *other* option (here, Other).
- **Every account in the final table.** The Accounts sheet (and CSV) has one row per account in the input file: the
  result, or the stage it stopped at and why (accounts the crawl hasn't reached are listed too). The separate Stage
  log sheet is gone.
- **One-line rationale**: what decided it, the number behind it, main business, the pages naming the work ("Towing,
  92% sure. Main business: no. Pages: /24-hour-towing"); the website check is mentioned only when CRM details saved a
  low score.
- **Only differences from the label get checked.** When our industry matches the CRM or ZoomInfo label nothing would
  change in the CRM, so it needs no check however unsure the model was. Review = we differ AND our answer is unsure;
  Label differences = we differ and are sure; Non-core = main business No (a count to track). "Main business could go
  either way" is no longer a review reason: it never changes the industry. On the last 100-per-segment run: Review
  10 (was 206 on one sheet), Label differences 132, Non-core 95.
- **Website-check wording in plain sentences, same order.** Version 3 keeps the tested order (name check first, the
  "rate it near 1 even if..." cases after) in plainer words. On 28 known wrong sites and 50 hard real ones, asked
  fresh: same as the old wording (27 of 28 caught, 1 real rejected at 0.15). A version that put the lenient cases
  first let more wrong sites through. The 0.15 bar stays (0.20 rejected 3-4 real sites on fresh calls).
- **Fewer files:** site_checks.py merged into crawl_worker.py (only the crawler used it) and store.py into crawl.py
  (the crawl store is Phase 1's output). Every pattern and hard-to-follow step now has a plain explanation with
  examples. Checked: identical model input, identical Accounts and Stage log tables, 8 re-crawled sites the same.

## 2026-11-09
- **Website-check wording kept as tested.** A plainer rewrite let 3 of 10 known wrong websites score above 0.15, so
  the model still gets the old text; the code now lays it out one sentence per line with comments explaining each
  part (including `domains_reached`: the other web addresses the crawl was sent to).
- **Tidy-ups, no change to what the model sees:** "trade" is "segment" throughout the code; each segment's
  main-business examples live in its own definition (`main_true`, `main_false`); the unused
  lease_plus_doing_business_as column (in no input file) is gone; the camera-word filter on image file names is
  gone (it caught almost nothing: the junk labels are hash-like file names and social icons).
- **Readability rewrite, no behaviour change.** Every module rewritten in plain language with a clear opening
  explanation; the crawler's decisions read as ordered checks; the decision rule lives in one function
  (`decide.choose`). Checked: the model receives identical input (617 accounts, same hash), saved answers give the
  same decisions (2,496 rows), and 14 re-crawled sites gave the same statuses.
- **Who-does-the-work wording** rewritten as six numbered points in plain language, same rules. On 12 hand-off
  accounts no segment changed; brokers and companies that refer the work leaned slightly more to Other.
- **Confidence is a coloured cell** (green High 85%+, yellow Medium 70-85%, red Low under 70%) instead of a separate
  band column; the Guide sheet defines the colours.
- **Equipment takes priority.** When several industries fit, the one whose equipment most of the company's work
  needs (kept short: a stronger "name or headline doesn't count" line overstated it). Septic vs Light Construction follows from it:
  pumping, jetting and cleaning (septic, vacuum, jetter trucks) is Septic; installing septic systems and drain
  fields is digging work (excavators, backhoes), so an installer that doesn't pump is Light Construction. The
  wording had septic installation in both; on 10 septic accounts a precast-tank seller moved to Other (correct).
- **Reports**: grouped columns (answers, then confidence, then main business, then explanations), soft colours
  (bands, Match/Mismatch, agreement), and a Guide sheet with every column and the thresholds in use.
- **API keys come from environment variables** (DECISION1_API_KEY, JEV_API_KEY), loaded from a private `.env`
  file (git-ignored), not api_keys.json.
- **Model comparison rebuilt on today's pipeline** (compare.py): identical input, same questions and decisions;
  each model can get its own Other bar and safety net, and the report shows how many Others each model has at bars
  0.70-0.95. New sets: compare_20each (24 per segment) and zoominfo_100each_2 (118 per segment), no overlap.
- **Wording made consistent and less specific:** one general rule for a service the site offers as its own while
  naming another company that does it (count it: unclear who does the work), replacing a contradiction between the
  who-does-the-work block and the towing note; examples written for single accounts made general; "works alongside"
  (read as a partner) became "has another company do". Removing the broker detail from the main-business false
  examples made a booking network score as a main business, so it stays. On 10 known tricky accounts no segment
  changed; a restroom rental company went from the safety net to a clear Septic pick.
- **Two outputs** (from the brief): the Accounts sheet/CSV (our industry, confidence and band, main business, label
  match, our probability for the label's industry, a rationale) and an evidence log with every stage per account.
  The rationale is built from our own numbers, not asked of the model, so it always matches the decision. Main
  business stays Yes/No. The review queue holds disagreements with the label plus low-confidence answers.
- **The report re-applies today's thresholds to saved scores**, so a threshold change needs no new calls.
- **Other bar 0.80** (from 0.75): on the 100-per-segment run the only real business lost to Other (an auto repair shop
  offering its own 24-hour tow truck service) sat at 0.753; nothing else scored 0.75-0.80.
- **The crawler always reads the sitemap** (and robots.txt's sitemaps), so pages the menus don't link to are ranked
  with the rest. Files such as .txt, .csv and .log are skipped. Tried and dropped: MiniLM (sentence-transformers) for
  link matching: it caught fewer trade pages than model2vec (1 vs 16 on 20 sites) and added ~35 s of startup per
  worker. Crawl4AI's AdaptiveCrawler (statistical and embedding) stopped at the homepage on 6 of 10 sites.
- **Link ranking matches trades loosely** (`page_rules.TRADE_PHRASES`, embeddings): "restroom trailer", "labels",
  "skid steer work" count as trade pages, not only exact words. Shop pages naming a trade are ordinary pages, not
  filler; ?query copies of a page rank one tier lower; in Phase 2 near-empty pages go last. On 683 sites with more than
  20 pages: slightly more trade pages in the 20 fetched (7,183 vs 7,130), large gains on shop and town-page sites.
  On 422 accounts whose model input changed, 416 kept their segment (3 changed, 3 timed out).
- **Crawl speed: browser back to 20 pages, 150 s per site for every pass, 8 browser workers, and a site stops after
  4 pages in a row time out.** 40 pages / 240 s made Phase 1 take 33 min on 617 accounts. On the 20 sites where the
  shorter crawl drops a page naming one of our trades, no segment or main business changed.
- **Code restructured, no rule changes**: one job per file (store, site checks and the API call split out), data in
  `data/`, the keyword fallback for page ranking removed (model2vec is required), model comparison retired. The model
  receives exactly what it did before (checked on all 130 eval2 accounts).
- **Test set `data/zoominfo_100each.xlsx`**: 118 fresh accounts per ZoomInfo segment label and all 27 fresh Others
  (none crawled before, the 590-account random set included). The random set was 63% Light Construction, mostly
  builders and designers, so it said little about the other segments.
- **Earlier random set `data/zoominfo_500.xlsx`**: 590 random ZoomInfo accounts with a website, none crawled before
  (about 15% drop out as dead, parked or wrong websites).
- **Browser pass fetches up to 40 pages, with 240 s per site** (was 20 and 150 s): missing a page costs more than
  crawl time. Only big JavaScript sites take longer (27 of 810 crawled sites hit the old 20-page cap).
- **Other bar 0.75** (from 0.70): rescues a general contractor that sat at 0.70-0.81; on 178 accounts only one
  repair shop that tows on the side is still lost.
- **Main business mirrors the Other rules**: brokers, dealers, repair shops, designers score near 0; it names the
  segment's equipment as the kind of work meant, without requiring the site to name it.
- **Main business blocks Other**: an Other whose main business for some segment is 0.50+ gets that segment. True
  Others (brokers included) score 0.25 at most, so this is a safety net that costs nothing today.
- **Town pages that name one of our trades are service pages** ("/atv-towing-in-chicago"), not filler. They were
  ranked last and left out of the budget, so a shop's only towing evidence never reached the model. Across 803
  crawled sites, a trade now appears only on left-out pages once (a plumber's blog post about tree roots).
- **Repair shops of any vehicle** (motorcycles, ATVs, RVs, boats) count for towing on the same terms as auto shops.
- **Rental companies of restroom trailers/toilets are presumed to own and service their units** (a condition
  pushed a trailer rental company to Other).

## 2026-11-06
- **Other needs p_other >= 0.70** (`decide.OTHER_THRESHOLD`). Losing a real business to Other costs more than a wasted
  call. On both eval runs true Others scored 0.9+, while real businesses wrongly given Other scored 0.55-0.8. Judged
  on the model's probability for Other, not its confidence field (a separate output that doesn't always agree).
- **Decision-1, not Jev.** On the fresh 119-account set they agreed on 109. Jev caught two businesses Decision-1
  lost, but gave 7 true Others a segment and scored true Others only 0.6-0.7, so a threshold separates them poorly.
  Jev is also an external endpoint.
- **Equipment dealers and repair shops are Other** (a jetter dealer, a boom-truck repair shop): they sell or fix the
  equipment, they don't do the work with it.
- **Irrigation and yard drainage are Landscape work**: irrigation contractors trench and grade.
- **A construction company whose headline doesn't say what it builds is judged by the services it lists.**
- **Interior-only remodelers are Other**: kitchens, baths, cabinets, flooring and painting need none of our
  equipment.
- **Light Construction main business** examples match the definition: residential GCs and design-build firms that
  renovate with their own crews, site-work and site-utility contractors, foundation contractors.
- **Septic vs Light Construction is decided by the equipment**: pumping, jetting and repairing lines is Septic;
  digging with excavators or a hydrovac (site utilities, new mains) is Light Construction.
- **Brokers and booking networks are Other** ("orders filled by local operators").
- **Auto shops and towing**: a shop that offers towing as its own service or takes tow requests on its own number
  counts; one that only arranges or helps pay for a tow doesn't.
- **Wording stays general.** A rule is added only for a pattern seen across several accounts, never for one case:
  one-off wording fixed one account and broke others.

## 2026-11-04 / 05
- **Main business is Yes/No** (from 0.40), blank for Other.
- **Website check by business name, not address** (CRM addresses are often billing or old). CRM phone, ZIP or email
  domain on the site always passes. Below 0.15 the account isn't classified and is listed for CRM clean-up.
- **Unclear evidence counts.** Other needs no evidence at all, or a clear hand-off.
- **Pages:** home first, then who-they-are and what-they-do pages, ordered inside each group by how much the page
  describes the company's work (embeddings), within a 24,000-token budget per call.

## 2026-10-29
- **The segment is the equipment we could finance**, even for a side line (except Light Construction, which must be
  the main work).
