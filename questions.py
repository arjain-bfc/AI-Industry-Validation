"""Every word Decision-1 is asked, in one place.

  DEFINITIONS        the five segments: the equipment we finance, the work it's used for, who counts, what doesn't
  OTHER              when the answer is Other
  WHO_DOES_THE_WORK  only work the company does itself counts; hand-offs don't; unclear evidence counts
  MAIN_WHO, ...      the main-business statement, built from each segment's definition
  SITE_MATCH         is this website the company's?
  QUESTIONS          all of the above, as sent with every call

Each segment is defined once. Both questions are built from that definition, so they can't drift apart:
  industry        which segment's equipment the company uses for its own work (Other = none)
  main_<segment>  is that segment's work the company's MAIN business
Parts of a definition: equipment and includes (industry question only), work and excludes (both questions),
main_true and main_false (examples for the main-business question: is this the company's MAIN work, or a side line).

After editing: restart the notebook kernel and start a new answers file. classify.RESERVED_TOKENS assumes the
questions take about 7,000 tokens.
"""
DEFINITIONS = {
    "decorated_apparel": {
        "equipment": (
            "Decorated apparel equipment: embroidery machines, screen printing presses, direct-to-garment (DTG) or "
            "direct-to-film (DTF) printers, sign-making equipment (sign, banner and vehicle graphics printers, plotters, "
            "cutters), or other decorating equipment such as heat presses, vinyl cutters, sublimation printers, label "
            "printers and label looms, laser engravers, UV and wide-format printers, and pad printers"),
        "work": (
            "decorating, printing, embroidering, engraving, weaving or personalizing items such as shirts, hats, uniforms, team "
            "wear, bags, towels and home linens, promotional products, signs, custom or personalized labels, name tags, "
            "patches, transfers, decals, or manufactured parts"),
        "includes": (
            "embroidery and screen printing shops, print and sign shops, custom label and patch makers, personalization "
            "and monogram shops, promotional product and uniform companies that decorate in-house, online stores and "
            "brands that make embroidered, printed or personalized products themselves, and any other business running "
            "this equipment"),
        "main_true": (
            "a label, embroidery, screen printing, DTG/DTF printing or sign company, or a store whose main products "
            "are items it embroiders, prints or weaves itself"),
        "main_false": (
            "a promotional products reseller that has other companies decorate its items; a crafter who embroiders "
            "only by hand, with no machines"),
    },
    "landscape_hardscape": {
        "equipment": (
            "Landscape and hardscape equipment: commercial mowers, chippers, stump grinders, compact tractors, "
            "aerators, or landscape trucks"),
        "work": (
            "lawn care and commercial mowing, tree trimming and removal, stump grinding, brush chipping, planting, mulch "
            "and sod, snow plowing, installing pavers, patios and retaining walls, installing irrigation and yard "
            "drainage, or skid steer, mini excavator, grading or hauling work for yards"),
        "includes": (
            "landscapers, lawn care and tree services, arborists that care for trees, irrigation contractors, "
            "property maintenance companies, "
            "and any other business doing this work"),
        "main_true": (
            "a lawn care, landscaping, hardscape or snow plowing company, a tree service, or an arborist that cares "
            "for trees"),
        "main_false": (
            "a landscape architect or designer that only designs; a builder or pool company that also does some "
            "landscaping"),
    },
    "light_construction": {
        "equipment": (
            "Light construction equipment: backhoes, excavators from mini to full-size, skid steers and compact track "
            "loaders, dozers, trenchers, wheel loaders, hydro excavation (hydrovac) trucks, or boom trucks and small "
            "cranes"),
        "work": (
            "smaller residential and light commercial jobs such as renovations, additions and room add-ons, patios, "
            "decks, driveways and concrete flatwork, residential and small commercial concrete foundations, footings "
            "and slabs, regrading and drainage, site preparation, excavation, grading and land clearing, hydro or "
            "vacuum excavation (potholing, daylighting and slot trenching to expose buried lines), "
            "demolition and tear-outs, foundation repair, trenching, installing septic systems and drain fields, "
            "residential or commercial roofing and siding, "
            "fencing, or small buildings such as garages, accessory dwelling units (ADUs), pole barns, sheds and steel or "
            "post-frame outbuildings"),
        "includes": (
            "renovation, remodeling and home improvement contractors, residential and commercial roofing and siding "
            "contractors, pole barn and steel building erectors, excavation, grading and site-work contractors, septic "
            "system installers, "
            "residential and small commercial concrete contractors, "
            "residential general contractors that renovate homes with their own crews, and any other business whose "
            "main work is this kind of work"),
        "excludes": (
            "Light construction must be the company's main work, judged by what it mainly presents itself as doing: "
            "its headline, its main services and the projects it shows. A company that mainly presents renovation, "
            "remodeling, roofing, site work or other work above counts, even if it also builds some new homes or does "
            "some commercial work. When a company offers both building and remodeling, its name and headline decide: "
            "one that leads with renovating or remodeling is light construction; one that leads with building, or "
            "presents itself as a building contractor that builds and remodels, is a builder. A construction company or "
            "general contractor whose headline does not say what it builds is judged by the services it lists: when "
            "most of them are work above, it counts, even if new homes or commercial buildings are among them. Not light "
            "construction: companies that mainly build new homes or housing "
            "developments (building new homes is heavy construction), developers, real estate companies, general "
            "contractors for large commercial buildings, heavy civil construction (highways, bridges, large utility "
            "projects, mining) and structural concrete for high-rises, garages or bridges. Interior-only work "
            "(kitchens, bathrooms, cabinets, flooring, painting) needs none of this equipment, so it is not light "
            "construction either. Where this overlaps with septic work, judge by the equipment: pumping, jetting and "
            "cleaning septic systems, sewers and drains needs septic trucks and is septic; digging with excavators, "
            "backhoes or a hydrovac truck (installing septic systems and drain fields, site utilities, new mains, "
            "exposing buried lines) is light construction."),
        "main_true": (
            "a roofing, siding, pole building, steel building, renovation or remodeling contractor that builds "
            "additions or does exterior, structural or site work; a residential general contractor or design-build "
            "firm that renovates homes with its own crews; an excavation, grading, site work, site utility or septic "
            "system installation contractor; a residential concrete or foundation contractor pouring or installing "
            "foundations, slabs and driveways"),
        "main_false": (
            "a company that mainly builds new homes, even if it also remodels; a general contractor for large "
            "commercial buildings; a developer; a remodeler or cabinet maker that only does interior work such as "
            "kitchens, baths, cabinets, flooring or painting"),
    },
    "septic": {
        "equipment": (
            "Septic equipment: septic pumper, vacuum or jetter trucks, vacuum tank trailers, or portable restroom "
            "trailers"),
        "work": (
            "septic tank and cesspool pumping, cleaning and servicing, grease trap pumping, portable toilet service, "
            "storm drain, catch basin and dry well cleaning, sewer and drain line cleaning and jetting, or industrial "
            "vacuum and cleaning services (pumping and hauling liquid waste, hydro jetting and blasting, tank and pipe "
            "cleaning)"),
        "includes": (
            "septic, portable toilet and drain companies, including portable toilet, restroom trailer and holding tank "
            "rental companies (they own, deliver and service their units, even if they send septic tank pumping to "
            "another company), septic pumping and aerobic system maintenance providers, industrial cleaning and vacuum "
            "service companies that run their own vacuum trucks, and plumbers doing this work"),
        "main_true": (
            "a septic pumper, an aerobic system maintenance company, a portable toilet or restroom trailer rental "
            "company, a drain cleaning and sewer line company, or an industrial vacuum and hydro blasting company"),
        "main_false": (
            "a plumber whose main work is plumbing and that also jets drains; a septic inspector that does not pump; "
            "a septic installer that does not pump (installing is digging work, light construction)"),
    },
    "towing": {
        "equipment": (
            "Towing equipment: tow trucks, wreckers, rollbacks or flatbeds, rotators, wheel-lift self-loaders and "
            "repo trucks, or car carriers (car hauler trucks and car hauler trailers)"),
        "work": (
            "towing, roadside assistance done with a tow truck or wrecker, accident recovery and winch-outs, vehicle "
            "transport on a rollback, flatbed or car carrier (auto transport and car hauling), vehicle repossession, "
            "or impound. Roadside help with no tow truck (jump starts, tire "
            "changes, lockouts, fuel delivery from a service van) is not towing"),
        "includes": (
            "towing companies, auto transport and car hauling companies, repossession companies, and repair shops, "
            "body shops, dealers and transporters of any vehicles (cars, trucks, motorcycles, ATVs, RVs, boats) that "
            "tow or haul vehicles"),
        "excludes": (
            "A repair shop, body shop or dealer of any vehicles counts when it presents towing as a service of its own (its own towing page "
            "or \"24 hour towing\" among its services) or takes tow requests on its own number (\"Need a tow? Call "
            "us\"). One that only mentions towing in passing as "
            "help it gives customers (towing assistance, or arranging, referring or helping pay for a tow), or says a "
            "tow company does its towing, does not."),
        "main_true": (
            "a tow company, wrecker service, roadside recovery company, vehicle transporter or car hauler, or a "
            "repossession company"),
        "main_false": (
            "an auto repair, tire or body shop that also tows, however prominently, unless towing is in its name or "
            "main headline; a truck shop that repairs or sells tow truck equipment to towing companies"),
    },
}
SEGMENTS = list(DEFINITIONS)

OTHER = (
    "None of the listed equipment: no evidence the company uses, or does work that requires, any of the equipment "
    "above, however close its industry looks. Also Other: companies whose site clearly says all of the listed work is "
    "done by third parties rather than by the company itself (they arrange, refer, schedule or pay for it, including "
    "brokers and booking networks that have local providers do the work), companies that only design, "
    "plan, inspect or supply materials for the work, companies that only sell or repair the equipment "
    "(dealers and repair shops), home builders that mainly present themselves as building new "
    "homes (even with some remodeling), developers, and real estate or property companies, even when they build or renovate "
    "homes (a contractor that renovates homes for owners or investors is not a real estate company)")

# Who does the work. Only a company that does the work itself buys the equipment, so work it hands to another company
# doesn't count. Losing a real business costs more than a wasted call, so when the site doesn't say who does the
# work, the company gets the benefit of the doubt: Other needs either no evidence at all, or a clear hand-off.
WHO_DOES_THE_WORK = (
    "Who does the work. Only work the company does itself, with its own people and equipment, counts: that is the "
    "company that would buy the equipment. "
    "(1) Work handed to another company does not count: when the site says the company arranges, refers, schedules, "
    "coordinates, subcontracts, resells or books it, or that a partner, a network or local providers do it (for "
    "example \"we can arrange a tow for you\" or \"printed by our partner\"). A broker, marketplace or booking "
    "network, or a company whose orders are filled by local operators or vendors, does none of the work itself, "
    "even if it says it delivers or serves customers nationwide. "
    "(2) Such wording rules out only the work it names. Everything else the company does itself still counts, even "
    "if the handed-off work is what the site talks about most (a company that has another company do one of its "
    "services but does the others itself still counts). "
    "(3) When the site both offers a service as its own (its own page for it, or requests taken on its own phone "
    "number) and names another company that does it, count it: it is unclear who does the work. Calling itself a "
    "customer's partner is not handing work off. "
    "(4) When the site does not say who does the work, assume the company does: a service it offers, lists or takes "
    "requests for on its own phone number is its own, and so are products it makes, prints or personalizes to "
    "order, whether or not the site names its machines or who installs or uses them. A business whose name or "
    "headline names the work does that work unless the site says otherwise; when the site says little else, the "
    "name and headline are enough. Trade associations and directories do not do the work they are named after. "
    "(5) These are never doing the work: work done only by hand with no sign of the equipment (but \"handmade\" "
    "alone does not rule out machines when the site also offers machine work); and designing, planning, inspecting "
    "or supplying materials, or selling, renting or repairing the equipment, when that is all the company does. A "
    "company that also installs, builds or carries out the work itself counts, even if most of its site is about "
    "the design or the supply. "
    "(6) Assuming the company does the work only settles who does it: it never makes a company count that the "
    "industry descriptions leave out.")

# Main business: kept short. The who-does-the-work rule is one sentence here (the full block's "benefit of the
# doubt" pushed side lines up), and each segment has its own true/false examples (shared ones leaked across segments).
MAIN_WHO = (
    "Only work the company does itself, with its own people and equipment, can be its main business; work it has "
    "another company do (arranges, refers, subcontracts), designs, inspects or supplies materials for is not, "
    "and a broker, marketplace or booking network that has local providers do the work does none of it itself. "
    "A company that designs or supplies and also does the work itself is judged by that work.")
MAIN_DECIDE = (
    "Decide from what the company mainly is: its name, its headline and the services or products it leads with on "
    "its home page; when there is no clear headline, the kind of services and projects it shows. Do not judge by how "
    "many pages or words are about this work: the pages shown were picked because they mention work like this, so "
    "they over-represent it. Rate this statement on its own, whatever industry was chosen above.")
def main_examples(d):
    """The main-business examples: the segment's own true and false examples, then what is always false."""
    true, false = d["main_true"], d["main_false"]
    return (f"True: this work is what the company mainly does or sells, for example {true}. When this work is clearly "
            "what the company is, rate it near 1: do not lower it because the site also mentions other services, "
            f"inspections, contracts or products. False: the company's main business is something else, even if it "
            f"also does this work itself, for example {false}. Also false, rated near 0, when the company does not "
            "do this work with its own equipment: it books, brokers, arranges or refers the work to other companies "
            "(a booking network or broker whose local providers or operators do the jobs), only sells, rents out or "
            "repairs the equipment, or only designs, plans or inspects the work (a design-build company that also builds "
            "or renovates with its own crews does the work); and when its main business is a "
            "different trade, or the site shows no sign of this work.")


def criterion(d):
    """The definition as one option of the industry question."""
    return " ".join([f"{d['equipment']}, used for {d['work']}. Includes {d['includes']}.",
                     d.get("excludes", "")]).strip()


def main_statement(segment, d):
    """The main_<segment> statement: is this segment's work the company's MAIN business (yes/no). Same work list
    and excludes as the industry question; who-does-the-work in one sentence (MAIN_WHO), not the full block; this
    segment's own true/false examples last."""
    return " ".join([f"This company's main business is doing this work itself: {d['work']}. This is the work that "
                     f"needs equipment like this ({d['equipment']}); the site does not have to name the equipment.",
                     MAIN_WHO,
                     d.get("excludes", ""), MAIN_DECIDE, main_examples(d)]).strip()


INDUSTRIES = {**{segment: criterion(d) for segment, d in DEFINITIONS.items()}, "other": OTHER}

# Is this website the company's? Judged by business name, not address (CRM addresses are often billing or old).
# decide.WRONG_SITE_BELOW turns it into a yes/no.
# Is this website the company's? Judged by business name, not address (CRM addresses are often billing or old);
# decide.WRONG_SITE_BELOW turns the answer into yes or no. website.domains_reached is added by classify.build_state
# when the crawl was sent on to other web addresses (a company that moved domain, or a domain now used by someone
# else). Tested  on 28 known wrong websites and 50 hard real ones: same results as the older wording. The
# order matters: the name check comes first and the "rate it near 1 even if..." cases after; a version that put
# those cases first let more wrong websites through.
SITE_MATCH = (
    "This website is the company's own website: the company in the CRM record runs it. Decide by the business name "
    "first: compare the CRM company name (and company.doing_business_as, its DBA, when given) with the business name "
    "the site shows in its title, headline and logo text. If website.domains_reached is given, the site sent us on to"
    " other web addresses than website.url: decide whether those still belong to the same company. True: the site "
    "names the same business, even under a trade name, a DBA, a shortened name, initials, a possessive or plural "
    "form, or with an owner's name added (\"... by Doug Inc.\"); or the site shows no name but nothing points to "
    "another business. When the site's business name is the CRM name, rate it near 1 even if its address, city, state"
    " or phone number differ from the CRM record: CRM addresses are often billing, owner or old addresses. The same "
    "holds when the web address doesn't contain the name (springfieldautoparts.com for \"Smith's Auto Salvage\") and "
    "when some pages come from a service the company uses on its own site (a parts search, a booking or payment page,"
    " a website builder): a site whose title or headline is the company's name is its site. A company that names a "
    "related or partner company (for after-hours service, or a family company it hands some work to) is still on its "
    "own site. False: the site is clearly a different business with a different name, such as a national chain or "
    "platform page (an auto parts store, a truck rental company, a directory or listing site) or an unrelated company"
    " now using the web address; or there is no real business site: a parked, for-sale, placeholder, under-"
    "construction or empty directory page, or a default \"Hello world\" page with nothing else. Do not judge which "
    "industry the company is in, only whether this is its website.")

QUESTIONS = {
    "site_match": {"type": "noul", "instructions": SITE_MATCH},
    "industry": {
        "type": "choice",
        "instructions": (
            "An equipment lender finances the equipment listed under each industry. Choose the industry whose equipment "
            "this company uses or would buy, based on evidence in its name and website: work it offers, projects it "
            "shows, or equipment it mentions. The equipment does not have to be named if the work requires it. Only "
            "work the company does itself counts: work the site clearly says it arranges or that a third party does "
            "for it is not evidence, because the company would not buy the equipment. When it is unclear whether the "
            "company does the work itself, count it, unless the site says a third party does that specific work. Work the company does itself counts even if it is a side "
            "line or the company is in a different industry, except Light Construction, which must be the company's "
            "main work. If several fit, choose the industry whose equipment most of the company's work needs. "
            "Choose None only when there is "
            "no evidence of any listed equipment or work, or the site clearly says third parties do all of it; "
            "when it is only unclear who does the work, or others do just part of it, choose the industry. "
            + WHO_DOES_THE_WORK
        ),
        "criteria": INDUSTRIES,
    },
    **{f"main_{segment}": {"type": "noul", "instructions": main_statement(segment, d)}
       for segment, d in DEFINITIONS.items()},
}
