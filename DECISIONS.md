# Why the rules are what they are

The code says what happens; this file says why. Newest first.

## 2026-11-10
- **One confidence scale.** The model's confidence is its probability rescaled so a blind guess counts as 0:
  (p - 1/6) / (1 - 1/6), checked against 1,000+ saved answers (within 0.001). When a threshold overrides Other, the
  model gives no confidence for the segment we keep, so the code used to show that segment's plain probability: a
  different measure in the same column. Now the same formula is applied (`decide.to_confidence`, 0 under 1/6). Only
  those override rows change (28 of 504 on the last run), all lower; no segment, rule or colour band changed.
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
- **Earlier random set `data/zoominfo_500.xlsx`**: 590 random ZoomInfo accounts with a website, none crawled before (about
  15% drop out as dead, parked or wrong websites).
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
- **Other needs p_other >= 0.70** (`decide.OTHER_FROM`). Losing a real business to Other costs more than a wasted
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
