"""Which pages of a website are most useful for telling what the company does.

Used twice, so the two always agree:
  - the crawler, to choose which links to fetch first when a site has more pages than the page limit;
  - Phase 2, to choose which fetched pages go to the model first when they don't all fit.

Every page gets a rank from its address (and, while crawling, the link's text). Lower ranks go first:
  HOME_PAGE        the home page
  ABOUT_US         who the company is: about, contact, team, history
  NAMES_OUR_SEGMENT  names one of our segments: towing, septic, roofing, embroidery, landscaping, ...
  WHAT_WE_DO       general "what we do" pages: services, equipment, fleet, projects, gallery
  ORDINARY         any other page
  FILLER           blog, news, careers, coupons, shop items, pages for single towns, translated copies
A few exceptions: a shop item or town page that names one of our segments is not filler; a copy of a page that differs
only in what follows "?" ("/get-a-quote?prod=mugs") ranks one step lower than the page itself; and after six
look-alike pages (same folder, or the same first word, like 30 "/towing-in-<town>" pages) the rest move down a
rank, so one family of pages can't crowd out the rest.

Phase 2 also reads each page's own text (menus and footers removed). Within a rank, pages that describe the company's
work come first, and pages with almost no text of their own (empty forms, error pages) go last.
"""
import re
from collections import Counter
from functools import lru_cache
from urllib.parse import urlparse

import numpy as np

HOME_PAGE, ABOUT_US, NAMES_OUR_SEGMENT, WHAT_WE_DO, ORDINARY, FILLER = -1, 0, 1, 1.5, 2, 3

# --- Words in page addresses -------------------------------------------------------------------------------------
# How to read the patterns: a|b means a or b; -? means an optional dash, so who-?we-?are matches "whoweare" and
# "who-we-are"; services? means "service" or "services"; ^ and $ are the start and end of the address;
# [^/]+ means one or more characters that are not a slash (one part of the address); re.I ignores upper/lower case.
# A word matches anywhere in the address unless ^ or $ pins it, so "about" catches /about, /about-us, /about/team.
#
# About the company: /about-us, /contact, /who-we-are, /our-story, /team, /history, /get-in-touch, /directions,
# and /locations on its own (but /locations/denver is a town page, below)
ABOUT_WORDS = re.compile(r"about|contact|who-?we-?are|our-?(story|company|team|people|history)|team|staff|history|"
                         r"get-?in-?touch|reach-?us|find-?us|directions|^/locations?$", re.I)
# What the company does, in general: /services, /our-work, /what-we-do, /capabilities, /equipment, /fleet,
# /gallery, /projects, /portfolio
WHAT_WORDS = re.compile(r"our-?(work|services?)|services?|what-?we-?do|capabilit|equipment|fleet|gallery|projects?|"
                        r"portfolio", re.I)
# Filler: /blog, /news, /press, /events, /careers, /jobs, /apply, /coupons, /specials, /community, one person's
# page (/team/john-smith), and translated copies: an address starting with a language code (/es/..., /fr-ca/...)
FILLER_WORDS = re.compile(
    r"blog|news|posts?/|articles?|press|events?|calendar|careers?|jobs?|employment|apply|coupon|specials?|"
    r"sitemap|results|community|happenings|/(staff|team|people|our-?team)/[^/]+|/help/|templates?|"
    r"^/(es|fr|de|it|pt|zh|ja|ko|ru|ar|vi|pl|nl|es-[a-z]{2}|fr-[a-z]{2})(/|$)", re.I)  # translated copies
# A US state or Canadian province code ending a page name ("/apple-valley-mn"). Codes that are also common words
# (in, or, me, oh, ok, hi, de, id, pa, al, la, co, ma) are left out, so "/sign-in" or "/drop-off" aren't towns.
STATE_AT_END = (r"-(ak|az|ar|ca|ct|fl|ga|ia|il|ks|ky|md|mi|mn|mo|ms|mt|nc|nd|ne|nh|nj|nm|nv|ny|ri|sc|sd|tn|tx|ut|"
                r"va|vt|wa|wi|wv|wy|ab|bc|mb|nb|ns|on|qc|sk)$")
# A page for one town. Town names can't be listed, so it is recognised by the shape of the address:
#   "-in-" or "-near-" before the last words      /towing-in-chicago, /septic-pumping-near-austin-tx
#   a page inside a places folder                  /service-areas/plano, /locations/denver, /cities/tulsa
#   "service area" anywhere                        /our-service-area
#   a state code at the end (STATE_AT_END)         /apple-valley-mn
TOWN_PAGE = re.compile(r"-(in|near)-[a-z0-9-]+$|/(cities|areas?|service-?areas?|locations?)/[^/]+|service-?area|"
                       + STATE_AT_END, re.I)
# A shop item or listing: /products/blue-cap, /collections/labels, /shop/..., /store/..., /catalog, /brands/...
SHOP_PAGE = re.compile(r"/products?/[^/]+|/shop/|/store/|/collections?/[^/]+|/catalog|/brands?/|/items?/", re.I)
# What follows "?" when it names a page of its own: WordPress addresses like "/?page_id=12" or "/?p=40" are
# real pages. Anything else after "?" ("/get-a-quote?prod=mugs") makes a copy of a page we already have.
OWN_PAGE_AFTER_QUESTION_MARK = re.compile(r"(^|&)(page_id|p|id|page)=[^&]", re.I)
FILE_ENDING = re.compile(  # /about-us.html and /about-us are the same page
    r"\.(html?|php|aspx?|jsp)$", re.I)

# --- Our segments ----------------------------------------------------------------------------------------------------
# Word stems that name one of our segments in a page address or link text: an exact match. A stem matches any word
# that contains it: "landscap" catches landscaping, landscaper, landscapes. A few need care, written as patterns:
#   (?<![a-z])signs?(?!in|up|ature)  "sign" or "signs" not inside another word, and not directly followed by
#                                    "in", "up" or "ature": /signs and /yard-signs match; /design, /signature and
#                                    /signin don't (/sign-in with a dash does, but the crawler skips login pages)
#   (?<![a-z])trees?                 "tree" or "trees" not inside another word: /tree-service, not /street
#   (?<![a-z])tow(?!n|er|el)         "tow" not inside another word, and not town, tower or towel: /towing and
#                                    /tow-truck match, /downtown and /towel-rack don't
#   screen-?print, pole-?(barn|building)   with or without a dash
# (?<![a-z]) means "no letter just before"; (?!...) means "not followed by".
# To add a segment, add it here, in SEGMENT_PHRASES and in questions.py.
SEGMENT_WORDS = {
    "decorated_apparel": [r"embroider", r"screen-?print", "apparel", "shirt", "decorat",
                          r"(?<![a-z])signs?(?!in|up|ature)", "signage", "vinyl", "dtf", "dtg", "decal", "label",
                          "patch", "uniform"],
    "landscape_hardscape": ["landscap", "lawn", "mow", r"(?<![a-z])trees?", "stump", "hardscap", "paver", "snow"],
    "light_construction": ["roof", "remodel", "renovat", "construct", "excavat", "grading", "concrete",
                           r"pole-?(barn|building)", "steel"],
    "septic": ["septic", "pump", "drain", "sewer", "portable", "toilet", "restroom", "porta", "grease"],
    "towing": [r"(?<![a-z])tow(?!n|er|el)", "wreck", "recover", "roadside"],
}
SEGMENT_WORD = re.compile("|".join(w for words in SEGMENT_WORDS.values() for w in words), re.I)
# Plain phrases for what our customers' pages are called. A link also counts as naming one of our segments when its
# words are close in meaning to one of these (a loose match: "restroom trailer", "skid steer work", "labels").
SEGMENT_PHRASES = {
    "decorated_apparel": [
        "embroidery", "monogramming", "screen printing", "custom t-shirts", "custom apparel", "hats and caps",
        "uniforms", "team wear", "promotional products", "heat transfers", "dtf transfers",
        "direct to garment printing", "sublimation", "vinyl decals", "stickers", "custom labels", "woven labels",
        "patches", "signs", "banners", "vehicle wraps", "vehicle graphics", "engraving", "print shop",
        "personalized gifts"],
    "landscape_hardscape": [
        "landscaping", "landscape design and installation", "lawn care", "mowing", "lawn maintenance", "fertilization",
        "aeration", "tree service", "tree removal", "tree trimming", "stump grinding", "brush chipping",
        "land clearing", "storm cleanup", "mulch", "sod installation", "irrigation", "sprinkler systems",
        "yard drainage", "hardscaping", "pavers", "patios", "retaining walls", "snow removal", "snow plowing"],
    "light_construction": [
        "excavation", "grading", "site work", "site preparation", "skid steer work", "bobcat services",
        "mini excavator", "backhoe services", "trenching", "hydro excavation", "demolition", "concrete", "foundations",
        "flatwork", "driveways", "roofing", "siding", "home remodeling", "renovations", "home additions", "decks",
        "fencing", "pole barns", "steel buildings", "garages", "utility installation"],
    "septic": [
        "septic tank pumping", "septic service", "septic installation", "septic inspection", "drain field",
        "drain cleaning", "sewer cleaning", "hydro jetting", "sewer camera inspection", "grease trap cleaning",
        "vacuum truck services", "portable toilets", "porta potty rental", "restroom trailers", "portable sinks",
        "hand wash stations"],
    "towing": [
        "towing", "tow truck service", "roadside assistance", "wrecker service", "heavy duty towing",
        "vehicle recovery", "accident recovery", "winching", "flatbed towing", "car hauling", "vehicle transport",
        "lockouts", "jump starts", "tire changes", "fuel delivery", "impound", "junk car removal"],
}
SEGMENT_MATCH = 0.55  # how close in meaning (0-1) a link must be to one of SEGMENT_PHRASES to count

# --- Limits --------------------------------------------------------------------------------------------------------
ABOUT_PAGES_PER_GROUP = 3  # about/contact-type pages per look-alike group; more count as ordinary pages
LOOK_ALIKES_PER_GROUP = 6  # look-alike pages before the rest move down a rank
MENU_LINE_SHARE = 0.4      # a line found on this share of a site's pages (and on 3 or more) is menu or footer text
EMPTY_PAGE_WORDS = 20      # Phase 2: a page with fewer words of its own than this goes last
EMBEDDING_MODEL = "minishlab/potion-base-8M"  # model2vec: a small model that compares meaning (pip install model2vec)


# --- Addresses -----------------------------------------------------------------------------------------------------
def clean_path(url_or_path):
    """'https://x.com/About-Us.html?x=1' or '/About-Us.html' -> '/about-us'."""
    path = urlparse(url_or_path).path if "://" in url_or_path else url_or_path.split("?")[0]
    return FILE_ENDING.sub("", path.lower()).rstrip("/") or "/"


def group(url_or_path):
    """Which look-alike group a page belongs to, so one family of pages can't crowd out the rest:
      in a folder: the folder         /floor-plans/ranch, /floor-plans/cape   -> 'floor-plans'
      otherwise: the first word       /towing-in-plano, /towing-in-allen      -> 'towing'
      a first word under 3 letters, or the home page                          -> '' (no group)"""
    path = clean_path(url_or_path).strip("/")
    if "/" in path:
        return path.split("/")[0]
    first_word = re.split(r"[-_]", path)[0]
    return first_word if len(first_word) >= 3 else ""


# --- Does a link name one of our segments? ---------------------------------------------------------------------------
_model, _phrase_vectors = None, None


def embedding_model():
    """model2vec, loaded once (downloaded the first time, ~30 MB)."""
    global _model
    if _model is None:
        from model2vec import StaticModel
        _model = StaticModel.from_pretrained(EMBEDDING_MODEL)
    return _model


@lru_cache(maxsize=100_000)
def closeness_to_our_segments(words):
    """0-1: how close in meaning these words are to the nearest of SEGMENT_PHRASES."""
    global _phrase_vectors
    model = embedding_model()
    if _phrase_vectors is None:
        vectors = model.encode([phrase for phrases in SEGMENT_PHRASES.values() for phrase in phrases])
        _phrase_vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    v = model.encode([words])[0]
    return float(np.max(_phrase_vectors @ (v / max(np.linalg.norm(v), 1e-9))))


def segment_score(url_or_path, text=""):
    """0-1: how clearly a link (its address and text) names one of our segments. 1 = a SEGMENT_WORDS match."""
    words = " ".join(re.findall(r"[a-z0-9]+", f"{clean_path(url_or_path)} {text or ''}".lower()))
    if not words:
        return 0.0
    if SEGMENT_WORD.search(words.replace(" ", "-")) or SEGMENT_WORD.search(words):
        return 1.0
    return closeness_to_our_segments(words)


# --- A page's rank -------------------------------------------------------------------------------------------------
def base_tier(url_or_path, text=""):
    """The page's rank from its address and link text alone (before look-alike limits)."""
    path, after_question_mark = clean_path(url_or_path), url_or_path.partition("?")[2].split("#")[0]
    if after_question_mark and not OWN_PAGE_AFTER_QUESTION_MARK.search(after_question_mark):
        # A copy of another page ("/get-a-quote?prod=mugs"): one rank lower than the page itself
        return FILLER if path == "/" else min(rank_by_path(path, text) + 1, FILLER)
    return rank_by_path(path, text)


def rank_by_path(path, text):
    if path == "/":
        return HOME_PAGE
    if FILLER_WORDS.search(path):
        return FILLER
    names_our_segment = segment_score(path, text) >= SEGMENT_MATCH
    if TOWN_PAGE.search(path):
        return NAMES_OUR_SEGMENT if names_our_segment else FILLER
    if SHOP_PAGE.search(path):
        return ORDINARY if names_our_segment else FILLER
    if ABOUT_WORDS.search(path) or ABOUT_WORDS.search((text or "").lower()):
        return ABOUT_US
    if names_our_segment:
        return NAMES_OUR_SEGMENT
    if WHAT_WORDS.search(f"{path} {(text or '').lower()}"):
        return WHAT_WE_DO
    return ORDINARY


def tier(url_or_path, text="", taken=None):
    """The page's rank once look-alike limits apply. taken: {group: pages already chosen from that group}.
    Example: a towing company with 30 pages like /towing-in-<town>. The first six rank as NAMES_OUR_SEGMENT; from the
    seventh on they drop a rank, so its /about, /services and /fleet pages still get their turn. About-type pages
    are limited to three per group the same way (more than three /team/<person> pages count as ordinary pages)."""
    rank = base_tier(url_or_path, text)
    page_group = group(url_or_path)
    already = (taken or {}).get(page_group, 0) if page_group else 0
    if rank == ABOUT_US and already >= ABOUT_PAGES_PER_GROUP:
        return ORDINARY
    if rank > ABOUT_US and already >= LOOK_ALIKES_PER_GROUP:
        return min(rank + 1, FILLER)
    return rank


# --- Phase 2: reading the pages' own text --------------------------------------------------------------------------
# Each page's own text is compared in meaning with this description of a company's work
DESCRIBES_THE_COMPANY = ("About the company: who it is, what it does, the products it makes or sells, the services it "
                         "offers, the equipment, trucks and machines it uses, the business it is in, the projects and "
                         "jobs it works on, and how it operates.")
CHUNK_WORDS = 150         # a page's text is compared in pieces of this many words...
WORDS_COMPARED = 600      # ...from its first 600 words
SHORT_PAGE_WORDS = 50     # pages shorter than this count for less


def page_bodies(pages):
    """{id(page): the page's own text}, in lower case, without the site's menus and footers.

    Menus and footers are found by repetition: a line that appears on at least 40% of the site's pages (and on at
    least 3 of them) is menu or footer text. With 20 pages, a line on 8 or more of them is dropped everywhere: a
    line like "Call us: 555-0100" in every footer goes, while a service description on one page stays."""
    def lines(page):
        return [line.strip().lower() for line in page["text"].splitlines() if line.strip()]

    pages_with_line = Counter(line for page in pages for line in set(lines(page)))  # each line counted once per page
    menu_lines = {line for line, n in pages_with_line.items() if n >= max(3, MENU_LINE_SHARE * len(pages))}
    return {id(page): " ".join(line for line in lines(page) if line not in menu_lines) for page in pages}


def relevance(pages):
    """{id(page): 0-1}: how closely each page's own text describes the company's work. In steps:
      1. take the page's own text (page_bodies: menus and footers removed), its first 600 words
      2. cut it into pieces of 150 words, and turn each piece into a vector (a list of numbers standing for its
         meaning) with model2vec; do the same for DESCRIBES_THE_COMPANY
      3. compare each piece with that description (cosine similarity: 1 = same meaning, 0 = unrelated), and
         average the pieces of a page
      4. scale short pages down: a page with 25 words of its own counts half (25 / SHORT_PAGE_WORDS)"""
    model = embedding_model()
    target = model.encode([DESCRIBES_THE_COMPANY])[0]
    target = target / np.linalg.norm(target)
    bodies = page_bodies(pages)
    pieces, piece_of = [], []
    for key, body in bodies.items():
        words = body.split()[:WORDS_COMPARED]
        for i in range(0, len(words), CHUNK_WORDS):
            pieces.append(" ".join(words[i:i + CHUNK_WORDS]))
            piece_of.append(key)
    scores = {key: 0.0 for key in bodies}
    if pieces:
        vectors = model.encode(pieces)
        similarity = (vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)) @ target
        for key in bodies:
            mine = [s for s, owner in zip(similarity, piece_of) if owner == key]
            if mine:
                scores[key] = float(np.mean(mine)) * min(1.0, len(bodies[key].split()) / SHORT_PAGE_WORDS)
    return scores


def order_pages(pages):
    """The order Phase 2 sends pages in: the home page; then by rank (look-alike limits applied as pages are chosen),
    and within a rank the pages that best describe the company's work; pages with almost no text of their own last."""
    scores = relevance(pages)
    nearly_empty = {key for key, body in page_bodies(pages).items() if len(body.split()) < EMPTY_PAGE_WORDS}
    remaining, ordered, taken = list(pages), [], {}
    while remaining:
        best = min(range(len(remaining)), key=lambda i: (remaining[i]["depth"] != 0,
                                                        id(remaining[i]) in nearly_empty,
                                                        tier(remaining[i]["path"], "", taken),
                                                        -scores[id(remaining[i])]))
        page = remaining.pop(best)
        ordered.append(page)
        page_group = group(page["path"])
        if page_group:
            taken[page_group] = taken.get(page_group, 0) + 1
    return ordered
