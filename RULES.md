# Industry Classification Rules

How each account is given an industry: what the model is asked, how its answers become a result, and the rules
behind every answer. The exact wording the model receives is in `questions.py`; the thresholds are in `decide.py`.

**In short.** Beacon finances equipment for five segments: Decorated Apparel, Landscape/Hardscape, Light
Construction, Septic and Towing. Each account gets the segment whose equipment the company uses or would buy, judged
from its own website, or Other when it uses none of it. The CRM and ZoomInfo industry labels are shown for comparison
but never used to decide.

## 1. What the model is asked, and what it answers

**One call per account: 7 questions, 12 numbers back.** The model never writes a free answer; every answer is a
probability.

**What goes in**

```
company    CRM name, DBA (doing business as), address
website    the web address and its best pages from the crawl: each page's address, title, text,
           image labels and link tooltips (about 11,000 words at most)
questions  the 7 questions below, with each segment's definition
```

**The questions, as asked** (all seven in the same call)

| # | Question | Answer |
|---|---|---|
| Q1 | **Industry:** which industry is this company most closely tied to, by the equipment it uses or would buy? | one of **Decorated Apparel / Landscape-Hardscape / Light Construction / Septic / Towing / Other**, with a probability for each; the six add up to 100% |
| Q2 | Is **Decorated Apparel** work this company's main business? | a 0–1 score |
| Q3 | Is **Landscape/Hardscape** work this company's main business? | a 0–1 score |
| Q4 | Is **Light Construction** work this company's main business? | a 0–1 score |
| Q5 | Is **Septic** work this company's main business? | a 0–1 score |
| Q6 | Is **Towing** work this company's main business? | a 0–1 score |
| Q7 | **Website check:** is this website the company's own? | a 0–1 score |

Q1 is one choice out of six, so its options compete. Q2 to Q6 are five separate yes/no questions: each score stands on
its own, so they don't add up, and several can be high (a company with two main lines of work) or all low (a company
whose main business is something else). Each is asked for every segment, whatever Q1's answer is.

**What each answer is used for**

| Answer | Used for |
|---|---|
| Q1 | the AI predicted industry and its Probability |
| Q2 to Q6 | Main business Yes/No for the chosen industry; the safety net that stops a real business going to Other |
| Q7 | spotting a website issue |

**A sample answer** (a collision shop with a towing page)

```
Q1 industry        Decorated Apparel 0.00   Landscape/Hardscape 0.00   Light Construction 0.00
                   Septic 0.00   Towing 0.29   Other 0.70                    (the six add up to 1)
Q2-Q6 main busin.  Decorated Apparel 0.00   Landscape/Hardscape 0.00   Light Construction 0.00
                   Septic 0.00   Towing 0.02                                 (each on its own)
Q7 website check   1.00
result             Towing, probability 29%, main business No
                   (the model leaned Other, but not strongly enough: see "Other needs to be sure")
```

## 2. How the answers become a result

| Result | Numbers used | Rule |
|---|---|---|
| **Website issue** (not classified) | website check | under **15%**: the site doesn't show this company (another business, an error or empty page, a placeholder, a domain taken over or sold). Always passes when the CRM phone, ZIP or email domain is on the site. Checked again only when the CRM web address changes, or in an occasional sweep |
| **Held back** (partial bot check) | Probability | a bot check let the crawl read only the home page, and the Probability is under **75%**: not classified, tried again on the next crawl |
| **AI predicted industry** | the 6 industry probabilities; for Other also the 5 main-business scores | the model's pick, except Other. **Other needs to be sure:** at least **80%** for Other, and every main-business score under **50%**. Otherwise the account gets its likeliest segment, because a missed customer costs more than an extra sales call |
| **Probability** | the industry probability of the result | High **90%** or more (green), Medium **75–90%** (yellow), Low under 75% (red, a close call) |
| **Main business** Yes / No | the chosen segment's main-business score only | Yes at **40%** or more; No means the company does the work alongside a different main business (non-core); blank for Other |
| **Review sheet** | Probability, and the CRM or ZoomInfo label | a segment under **50%** that differs from the label, or under **30%** that matches it |
| **AI probability for the CRM/ZoomInfo industry** | the industry probability of the label's option | shown only, never used to decide |

**Worked examples** (real numbers from the pilots)

| Company | Industry answer | Main-business answers | Result |
|---|---|---|---|
| An excavation contractor | Light Construction 100% | Light Construction 99% | Light Construction, main business Yes |
| An auto body shop with its own tow truck | Towing 97% | Towing 13% | Towing, main business No (non-core) |
| A collision shop with a towing page | Other 70%, Towing 29% | Towing 2% | Towing at 29%: Other is under 80%, so the likeliest segment; on the Review sheet |
| A print shop | Other 92%, Decorated Apparel 8% | Decorated Apparel 68% | Decorated Apparel: a main-business score of 50% or more blocks Other |
| A roadside-assistance app | Other 99% | all under 2% | Other |

## 3. General rules (all segments)

### The basic question

- **Equipment, not industry.** Pick the segment whose equipment the company uses or would buy, judged from its name and website: the work it offers, the projects it shows, the equipment it mentions.
- **The lists are examples, read as "any one of".** Each piece of equipment or work listed for a segment is evidence on its own; a company doesn't need to match the whole list.
- **The equipment doesn't have to be named.** Mowing lawns needs mowers, even if the site never says "mower".
- **Non-core work counts.** Work the company does itself counts even when it isn't its main business: an auto shop that tows with its own truck is Towing. The exception is construction contractors (see Light Construction).
- **When several segments fit,** choose the one whose equipment most of the company's work needs, counting the services it offers, not how often the site repeats them (service-area and location pages can repeat one service many times).

### Who does the work

- **Only work the company does itself, with its own people and equipment, counts.** That's the company that would buy the equipment.
- **Handed-off work doesn't count:** "we arrange, refer, schedule, subcontract, resell or book it", "a partner or local providers do it".
- **Brokers, marketplaces and booking networks do none of the work,** even if they say they serve customers nationwide.
- **A hand-off rules out only the work it names.** Everything else the company does itself still counts.
- **Offered as its own, with another company named: count it.** A service with its own page, or taken on the company's own phone number, counts. Calling itself "the customer's partner" isn't a hand-off.
- **Unclear who does the work: assume the company does.** A service it offers is its own; products it makes, prints or personalizes to order are its own, whether or not machines are mentioned.
- **The name or headline is enough** when the site says little else. A business named after the work does that work unless the site says otherwise.
- **Never doing the work:** work done only by hand, with no sign of equipment; only designing, planning, inspecting or supplying materials; only selling, renting or repairing the equipment. A company that also carries out the work counts.
- **Trade associations and directories** don't do the work they're named after.
- **Assuming the company does the work never brings in a company the segment definitions leave out.**

### When the answer is Other

- **Other means no evidence of any listed equipment or work,** however close the industry looks.
- **Also Other:** the site says third parties do all the work; real estate and property companies, even when they build or renovate (a contractor renovating homes for owners or investors isn't one). Designers, suppliers and dealers: see "Never doing the work"; builders: see Light Construction.
- **Unclear who does the work, or others do only part of it: choose the segment, not Other.** A wasted sales call costs less than a missed customer.

## 4. The five segments

### Decorated Apparel

| | |
|---|---|
| **Equipment** | embroidery machines, screen printing presses, DTG/DTF printers, sign-making equipment (sign, banner and vehicle-graphics printers, plotters, cutters), heat presses, vinyl cutters, sublimation printers, label printers and looms, laser engravers, UV and wide-format printers, pad printers, and the equipment that supports the decorating work, such as drying, screen-making and finishing equipment |
| **Work** | putting logos, designs or text onto items by printing, embroidering, engraving, weaving or personalizing them: apparel, bags, linens, promotional products, signs, labels, name tags, patches, transfers, decals, and manufactured parts (marking or decorating parts made by others) |
| **Who counts** | embroidery and screen printing shops; print and sign shops; label and patch makers; personalization and monogram shops; promotional product and uniform companies that decorate in-house; online stores and brands that make decorated products themselves |
| **Main business: yes** | a label, embroidery, screen printing, DTG/DTF or sign company, or a store whose main products are items it decorates itself |
| **Main business: no** | a promotional products reseller that has others decorate its items; a hand-only crafter |

### Landscape / Hardscape

| | |
|---|---|
| **Equipment** | commercial mowers, chippers, stump grinders, compact tractors, aerators, bucket trucks, landscape trucks |
| **Work** | lawn care and mowing, tree trimming and removal, stump grinding, brush chipping, planting, mulch and sod, snow plowing, pavers, patios and retaining walls, irrigation and yard drainage, skid steer or mini excavator work for yards |
| **Who counts** | landscapers, lawn care and tree services, arborists, irrigation contractors, property maintenance companies |
| **Main business: yes** | a lawn care, landscaping, hardscape or snow plowing company, a tree service, an arborist |
| **Main business: no** | a landscape architect or designer that only designs; a builder or pool company that also does some landscaping |

### Light Construction

| | |
|---|---|
| **Equipment** | backhoes, excavators (mini to full-size), skid steers and track loaders, dozers, trenchers, wheel loaders, hydrovac trucks, boom trucks and small cranes |
| **Work** | smaller residential and light commercial jobs: renovations and additions; patios, decks, driveways and flatwork; residential and small commercial foundations; regrading, drainage, site prep, excavation, grading and land clearing; hydro-excavation; demolition and foundation repair; trenching; roofing and siding; fencing; garages, ADUs, pole barns, sheds and steel buildings |
| **Who counts** | renovation and remodeling contractors, roofing and siding contractors, pole barn and steel building erectors, excavation and site-work contractors, residential concrete contractors, residential general contractors that renovate with their own crews; any other business doing this work itself, even as non-core work (a pool or restoration company that digs or roofs with its own equipment) |
| **Main business: yes** | a roofing, siding, pole/steel building or remodeling contractor; a residential general contractor that renovates with its own crews; an excavation or site-work contractor; a residential concrete or foundation contractor |
| **Main business: no** | a company that mainly builds new homes; a commercial general contractor; a developer; an interior-only remodeler or cabinet maker |

Special cases:

- **Construction contractors count only when light construction is their main work:** home builders, developers, general contractors for commercial, industrial or multifamily buildings, structural or commercial concrete contractors, civil or heavy contractors. Doing some renovation, concrete or site work doesn't make them Light Construction. Rebuilding homes, or building ADUs or additions as part of a home-building business, is still home building.
- **Builder or renovator? Weigh the headline with the services and projects.** Mainly renovating or remodeling: Light Construction, even if the headline says builder. Mainly building new homes or buildings: a builder (Other).
- **A headline that doesn't say what it builds:** judge by the services listed. Mostly light construction work counts, even with some new homes or commercial buildings among them.
- **Interior-only work** (kitchens, baths, cabinets, flooring, painting) needs none of this equipment, so it isn't Light Construction.
- **Where Light Construction and Septic overlap, judge by the equipment.** Pumping, jetting and cleaning needs septic trucks: Septic. Digging (installing septic systems, site utilities, exposing lines) needs excavators: Light Construction. A vacuum truck, hydrovac included, is judged by its use: digging with it (hydro excavation, potholing) is Light Construction; pumping and hauling liquids, sludge or waste with it (cleaning tanks and pipes, spill clean-up) is Septic. A company doing several of these goes to the equipment most of its work needs. This rule is stated once on purpose: repeating it across the definitions made it override companies whose whole business is septic systems.

### Septic

| | |
|---|---|
| **Equipment** | septic pumper, vacuum or jetter trucks, vacuum tank trailers, portable restroom trailers |
| **Work** | septic tank and cesspool pumping; grease trap pumping; portable toilet service; storm drain, catch basin and dry well cleaning; sewer and drain jetting; industrial vacuum work (liquid waste hauling, hydro blasting, tank cleaning) |
| **Who counts** | septic, portable toilet and drain companies; portable toilet, restroom trailer and holding tank rental companies, even if they send tank pumping elsewhere; aerobic system maintenance; industrial vacuum companies with their own trucks, even if they also offer hydro excavation; plumbers doing this work |
| **Main business: yes** | a septic pumper, aerobic maintenance company, portable toilet or restroom trailer company, drain and sewer cleaning company, industrial vacuum company |
| **Main business: no** | a plumber that also jets drains; a septic inspector that doesn't pump |

### Towing

| | |
|---|---|
| **Equipment** | tow trucks, wreckers, rollbacks and flatbeds, rotators, wheel-lift self-loaders and repo trucks, car carriers |
| **Work** | towing, roadside assistance with a tow truck, accident recovery and winch-outs, vehicle transport on a rollback or car carrier, repossession, impound |
| **Not towing** | roadside help with no tow truck (jump starts, tire changes, lockouts, fuel delivery) |
| **Who counts** | towing, auto transport, car hauling and repossession companies; repair shops, body shops, dealers and transporters of any vehicle that tow or haul vehicles |
| **Main business: yes** | a tow company, wrecker service, roadside recovery company, vehicle transporter or car hauler, repossession company |
| **Main business: no** | an auto repair, tire or body shop that also tows, unless towing is in its name or main headline; a truck shop that repairs or sells tow equipment |

Special cases:

- **A repair shop, body shop or dealer counts only when towing is its own service:** its own towing page, "24 hour towing" among its services, or "Need a tow? Call us" on its own number.
- **Towing mentioned only in passing doesn't count** (towing assistance; arranging or paying for a tow), nor does towing the site says a tow company does.

## 5. The main-business question

Asked once for each segment, separately from the industry question.

- **Only work the company does itself can be its main business.** Handed-off, designed, inspected or supplied work can't; brokers and booking networks do none of it. A company that designs or supplies and also does the work is judged by the work.
- **Decide from what the company mainly does:** its name and headline weighed together with the services it lists, the projects it shows and the rest of the site. Neither the headline alone nor any one page decides.
- **Don't judge by how many pages mention the work.** The pages sent were picked because they mention our work, so they over-represent it.
- **Rate each segment on its own,** whatever industry was chosen.
- **Near 1** when the work is clearly what the company is, even if other services are mentioned; **near 0** when it doesn't do the work with its own equipment, its main business is another trade, or there's no sign of the work.

## 6. The website check

Before the check, CRM links to social media, directories, review and lead-generation sites, company-data sites and
marketplaces aren't crawled at all. A company's own Facebook or Instagram page is crawled, narrowly: the page itself,
its About page and its own posts. The same goes for a company website that sends visitors on to Facebook or
Instagram; if it lands on a log-in page, the site counts as blocked and is tried again on the next run. Facebook's
own pages are never read.

- **Decide by business name first:** the CRM name and DBA against the name the site itself shows (title, headline, logo or page text), not just its web address.
- **The same business** even under a trade name, DBA, short name, initials, possessive or plural, or with an owner's name added.
- **No name on the site, and nothing pointing to another business:** the site is theirs.
- **The name matches and the site says what the business does:** theirs, even if the address or phone differ from the CRM (CRM addresses are often billing, owner or old addresses).
- **Still theirs:** a web address without the name; pages from a booking, payment or website-builder service; a site naming a related or partner company; the company's own Facebook or Instagram business page.
- **Redirects:** if the site sends the crawler on to other web addresses, check they still belong to the same company.
- **Not theirs:** a different business (a national chain, a platform page, an unrelated company now using the address); a directory, review, marketplace or lead-generation listing; another business's social media page or a personal profile; no real business site (parked, for sale, placeholder, under construction, empty), even when it shows the company's name.
- **The website check never judges the industry.**
- **A site that fails the check is a "website issue",** whatever the cause, shown with what the page says. It is not tried again on its own: only when the CRM web address changes, or in an occasional sweep.
