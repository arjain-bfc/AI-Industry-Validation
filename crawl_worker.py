r"""The crawler: fetches a list of websites and writes one line per website to a results file.

crawl.py starts several copies of this script at once, as separate processes, and gives each its share of the
sites:  python crawl_worker.py <job.json> <results.jsonl>

Each website goes through up to three passes (the job says which one this copy runs):
  "http"          a plain, fast download, several sites at once. Settles most sites. A site that refused us,
                  failed, or gave back one near-empty page (often a site built with JavaScript) is handed on.
  "browser"       a real (hidden) Chrome browser, one site at a time. Still refused or timed out: handed on.
  "browser_hard"  a last try with Crawl4AI's "undetected" browser in a visible window, with longer waits.

For every site: fetch the home page, then the pages it links to on the company's own domain and the pages in its
sitemap, most useful first (page_rules.py), until the page limit or the site's time limit. Pages fetched before
time runs out are kept. A company's own Facebook or Instagram page is fetched narrowly instead (section 3).

The sections:
  1. which links to follow               5. what did we get: each pass's verdict
  2. a fetched page, as stored              (the checks themselves are in site_checks.py)
  3. Facebook and Instagram pages        6. the browsers
  4. fetching one website                7. the passes

How to read the patterns (regular expressions) in this file:
  a|b   a or b                          (s)?   the s is optional: "cookie" or "cookies"
  \b    the edge of a word              [0-7]  any one of the digits 0 to 7
  \s    a space                         .*     anything (any number of characters)
  ^ $   the very start / very end       \.     a real dot (a plain . means any character)
re.I means upper and lower case are treated the same.
"""
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).parent))  # this script runs on its own: let it find our other files
import page_rules  # noqa: E402  which links to fetch first
from accounts import PROFILE_SITES, on_domain, social_profile  # noqa: E402
from crawl import append_line  # noqa: E402
from site_checks import (  # noqa: E402
    DOMAIN_NOT_FOUND, FILTER_MESSAGE, PAGE_GONE, TRY_OTHER_ADDRESS, host_error_status, is_ad_redirect, is_bot_check,
    parked_by_plain_request, parked_reason, placeholder_reason, refusal_reason, stopped_by_our_filter,
    unreachable_reason, words)

os.environ.setdefault("CRAWL4AI_NO_CLOUD_NOTICE", "1")

import requests  # noqa: E402
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, UndetectedAdapter  # noqa: E402
from crawl4ai.async_configs import HTTPCrawlerConfig  # noqa: E402
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy, AsyncPlaywrightCrawlerStrategy  # noqa: E402
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator  # noqa: E402


# The plain download says it is an ordinary Chrome browser: many small-business hosts turn crawlers away (403)
CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/130.0.0.0 Safari/537.36")


# The browser waits until a "checking your browser" page has gone (in a real browser it clears by itself)
BOT_CHECK_CLEARED = ("js:() => !/just a moment|checking your browser|verify you are human|attention required/i"
                     ".test(document.title)")


SLOW_DOWN_SECONDS = 5  # after a site says "too many requests" (429): its pages one at a time, with this pause


GENTLE_PAUSE_SECONDS = 8  # "gentle" sites (a bot check stopped us last time): one page at a time, this far apart


NEARLY_EMPTY = 20      # fewer words than this across all pages: nothing usable came back


# ====================================================================================================================
# 1. Which links to follow
# ====================================================================================================================
# Links never followed. The address (the part after the domain) is checked for three things:
#   1. a skip word between separators (/ _ . - or the start/end), so whole words only:
#        /privacy-policy, /login, /my-account, /cart, /wp-admin/x   are skipped
#        /accounting, /design-installation, /cartography            are followed ("account" sits inside a word)
#      The words: legal pages, logins and sign-ups, carts and checkout, and website-builder plumbing (wp-..., feed,
#      cdn-cgi).
#   2. blog listing folders: /tag/..., /category/..., /author/..., and numbered listing pages /page/2
#   3. a file ending: .pdf .jpg .png .zip .docx .xlsx .mp4 .css .js .xml .txt .csv and other non-pages
SKIP_LINKS = re.compile(
    r"(^|[/_.-])(privacy|terms|cookies?|accessibility|log-?in|sign-?in|sign-?up|register|my-?account|account|cart|"
    r"checkout|wp-json|wp-content|wp-admin|wp-includes|xmlrpc|feed|cdn-cgi)([/_.-]|$)|/tag/|/category/|/author/|"
    r"/page/\d|\.(pdf|jpe?g|png|gif|webp|svg|zip|docx?|xlsx?|pptx?|mp3|mp4|mov|css|js|xml|json|ico|txt|csv|log|bak|"
    r"sql|gz|rar|exe|dmg|apk|woff2?|ttf|eot|map)$", re.I)


# Everything after "?" in an address is a list of name=value settings ("?utm_source=google&sort=price"). Some only
# track the visitor, sort, filter or page the same content, so they are removed and the page is fetched once:
#   /services?utm_source=google   -> /services         (ad tracking: utm_..., fbclid, gclid, msclkid, ...)
#   /shop?sort=price&order=asc    -> /shop             (sorting and filtering)
#   /events?month=5&year=2026     -> /events           (calendars)
# A name is matched whole: "^" and "$" mean start and end, ".*" means anything after (utm_.* = utm_source,
# utm_campaign, ...).
SAME_PAGE_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|gbraid|wbraid|gad_source|msclkid|yclid|srsltid|_ga|_gl|"
                              r"mc_[a-z]+|ref|ref[a-z_]*id|referr?er.*|pcurl|source|src|campaign.*|sort|orderby|order|"
                              r"filter.*|replytocom|share|session.*|sid|phpsessid|amp|print|month|year|date|"
                              r"gridcookie|display|layout|mode|per_page|limit|tribe.*|ical|outlook-ical|hl|lang)$",
                              re.I)


# Page numbers: "?page=2" is just page 2 of a list (removed), but "?page=about" names a real page (kept)
PAGE_NUMBER = re.compile(r"^(page|paged|view|pg)$", re.I)


# Not pages at all, so the link is skipped: search results (?s=, ?q=, ?search=) and shop actions (?add-to-cart=,
# ?wishlist=, ?action=)
NOT_A_PAGE = re.compile(r"^(s|q|search.*|query|keywords?|add-to-cart|add_to_cart|wishlist|compare|action|"
                        r"redirect_to)$", re.I)


def page_path(url):
    """'https://x.com/services/' -> '/services'; the home page is '/'. Anything after '?' is kept: some sites tell
    their pages apart only by it ('/?page_id=12')."""
    parsed = urlparse(url)
    return (parsed.path.rstrip("/") or "/") + (f"?{parsed.query}" if parsed.query else "")


def site_domain(url):
    """'https://www.x.com:443/a' -> 'x.com'."""
    return urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")


def on_same_site(url, domain):
    host = site_domain(url)
    return host == domain or host.endswith("." + domain)


def clean_link(url):
    """The address to fetch, without tracking or sorting parts; None if it isn't a page worth fetching."""
    parsed = urlparse(url.split("#")[0].strip())
    if parsed.scheme not in ("http", "https") or SKIP_LINKS.search(unquote(parsed.path)):
        return None
    params = parse_qsl(parsed.query, keep_blank_values=True)
    if any(NOT_A_PAGE.match(name) for name, _ in params):
        return None
    kept = sorted((name, value) for name, value in params if not SAME_PAGE_PARAMS.match(name)
                  and not (PAGE_NUMBER.match(name) and value.strip().isdigit()))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", urlencode(kept), ""))


def home_page_addresses(url):
    """The home page as given, then with or without 'www', then over http: tried in turn when one won't connect."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    other = host.removeprefix("www.") if host.startswith("www.") else "www." + host
    rest = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    return list(dict.fromkeys([f"{parsed.scheme or 'https'}://{host}{rest}", f"https://{other}{rest}",
                               f"http://{host}{rest}", f"http://{other}{rest}"]))


def links_on_page(result, domain, seen):
    """[(address, link text)] for links to pages of the company's own site not seen yet, in page order."""
    found = []
    for link in (result.links or {}).get("internal", []) + (result.links or {}).get("external", []):
        url = clean_link(link.get("href") or "")
        if url and on_same_site(url, domain) and page_path(url).lower() not in seen:
            seen.add(page_path(url).lower())
            found.append((url, link.get("text") or ""))
    return found


def links_in_sitemap(home_url, domain, seen):
    """[(address, '')] for every page in the site's sitemap: sitemap.xml and any sitemap robots.txt names (an index
    of sitemaps is followed, up to 10). Finds pages the menus don't link to."""
    root = f"{urlparse(home_url).scheme}://{urlparse(home_url).netloc}"
    headers = {"User-Agent": CHROME}
    to_read, read, found = [f"{root}/sitemap.xml"], set(), []
    try:
        robots = requests.get(f"{root}/robots.txt", headers=headers, timeout=10).text
        to_read += re.findall(r"(?im)^sitemap:\s*(\S+)", robots)
    except requests.RequestException:
        pass
    while to_read and len(read) < 11:
        sitemap = to_read.pop(0)
        if sitemap in read:
            continue
        read.add(sitemap)
        try:
            xml = requests.get(sitemap, headers=headers, timeout=10).text
        except requests.RequestException:
            continue
        for address in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml):
            if re.search(r"\.xml(\?|$)", address):  # another sitemap
                to_read.append(address)
                continue
            url = clean_link(address)
            if url and on_same_site(url, domain) and page_path(url).lower() not in seen:
                seen.add(page_path(url).lower())
                found.append((url, ""))
    return found


# ====================================================================================================================
# 2. A fetched page, as stored
# ====================================================================================================================
def image_label(img):
    """The image's alt text, or else the words in its file name ('rollback-tow-truck_2.jpg' -> 'rollback tow
    truck')."""
    alt = re.sub(r"\s+", " ", img.get("alt") or "").strip()[:150]
    file_name = unquote(Path(urlparse(img.get("src") or "").path).stem).lower()
    return alt or " ".join(word for word in re.split(r"[^a-z]+", file_name) if len(word) >= 3)


# A link's title attribute (its hover tooltip) is not part of the page text. It's often the only words on an image
# button ("Repossession Scheduling" on a booking button), so it's kept, unless it adds nothing: it repeats the link's
# own text, it's one word, or it's generic.
GENERIC_LINK_TITLE = re.compile(r"^(home|click here|read more|learn more|see more|more info|menu|open|close|link|"
                                r"external link|opens? in a new (window|tab)|back to top|next|previous|go to .*|"
                                r"(visit|follow|like|find)( us)? on .*|posts? by .*|"
                                r"(facebook|instagram|twitter|youtube|linkedin) .*)$", re.I)


def link_titles(result):
    """The page's link tooltips that add something to its text (see above), each once."""
    found = []
    for link in (result.links or {}).get("internal", []) + (result.links or {}).get("external", []):
        title = re.sub(r"\s+", " ", link.get("title") or "").strip()[:150]
        text = re.sub(r"\s+", " ", link.get("text") or "").strip().lower()
        if (len(title.split()) >= 2 and title.lower() not in text and not GENERIC_LINK_TITLE.match(title)
                and title not in found):
            found.append(title)
    return found


def stored_page(result, url, depth, fetched_by):
    """One page as the crawl store keeps it. depth: 0 = home page, 1 = linked from it, and so on. The text is the
    whole page, never cut."""
    return {"url": url, "path": page_path(url), "title": (result.metadata or {}).get("title"), "depth": depth,
            "text": (result.markdown.raw_markdown if result.markdown else "") or "",
            "images": [{"label": image_label(img)} for img in (result.media or {}).get("images", [])],
            "link_titles": link_titles(result), "fetched_by": fetched_by}


def without_repeats(pages):
    """Drop repeated pages: the same address, or the same text under another address. Home page first."""
    kept, addresses, texts = [], set(), set()
    for page in sorted(pages, key=lambda p: p["depth"]):
        text = " ".join(page["text"].split()).lower()
        if page["path"].lower() in addresses or (text and text in texts):
            continue
        addresses.add(page["path"].lower())
        texts.add(text)
        kept.append(page)
    return kept


# ====================================================================================================================
# 3. A company's own Facebook or Instagram page
#
# Fetched narrowly: the page itself, its About page (Facebook) and its own posts, never other pages of the site (left
# alone, the crawler wanders into Meta's help pages and OTHER businesses' pages). Logged out, the useful part is short
# (intro, category, contact details, bio, post captions); the rest is menus and sign-up text, removed line by line.
# This applies however we got there: a Facebook/Instagram link in the CRM, or a company website that sends visitors on
# to Facebook/Instagram. Facebook and Instagram are never crawled like an ordinary website, and a page Facebook
# redirects away from the company's own (its About tab sent to Meta's corporate About page) is not kept.
# What Facebook shows instead of a page:
#   a log-in page          personal profiles, or Facebook slowing us down: "blocked", tried again on a later run
#   no company page        a website that sends visitors to Facebook's home or similar: "dead_site", tried again later
#   "This content isn't available right now"   deleted or friends only: "dead_site", tried again on a later run
#   "This page isn't available right now"      a glitch that often clears on a reload: reloaded twice
# ====================================================================================================================
MAX_PROFILE_PAGES = 8  # the page, its About page and a few of its own posts


LOGIN_WALL = re.compile(r"^/(login|accounts/login)(/|\.php|$)", re.I)


PAGE_GONE_SOCIAL = re.compile(r"this content isn.t available right now", re.I)


PAGE_UNAVAILABLE = re.compile(r"this page isn.t available right now", re.I)


# Pages under the company's address that are only lists of people, photos or videos
NOT_OWN_PAGE = re.compile(r"/(followers|following|friends|photos_albums|photos|reels_tab|reels|owner_reels|"
                          r"videos_tab|videos|mentions|likes|map|check_ins|about_profile_transparency|tagged|"
                          r"highlights)(/|$)|"
                          r"[?&]sk=(followers|following|friends|photos|photos_albums|reels_tab|videos|"
                          r"about_profile_transparency)", re.I)


# Facebook keeps a page's posts at addresses outside the page's own (/photo/?fbid=..., /permalink.php?...). Those
# linked from the company's page are its own recent posts. Logged out, most show only their date (the newest posts'
# text is on the page itself), but some still carry a caption, so a few are fetched within MAX_PROFILE_PAGES.
FACEBOOK_POST = re.compile(r"^/(photo|photo\.php|permalink\.php|story\.php|reel|videos?)(/|\?|$)", re.I)


# Site furniture: a line that is only one of these is dropped
SOCIAL_CLUTTER = re.compile(
    r"^(facebook|instagram|meta|log ?in|sign ?up|or|posts|about|photos|more|reels|videos|mentions|reviews|intro|"
    r"albums|followers|following|tagged|share|like|comments?|reply|follow|message|privacy|terms|advertising|"
    r"carousel|options|more options|close|save|popular|meta ai|muse|english|see more posts|"
    r"[\d.,]+[km]?( (followers|following|posts|likes|comments|shares|views))?|all reactions:?|"
    r"ad choices|cookies?|blog|jobs|help|api|locations|threads|meta verified|instagram lite|"
    r"forgot (account|password)\??|email or phone number|mobile number or email|password|create new account|"
    r"reload page|see all photos|see more on facebook|see more from .*|show more posts from .*|"
    r"more posts from .*|never miss a post from .*|sign up for instagram.*|log in to (like or comment|see).*|"
    r"load more comments|no comments yet\.?|be the first to comment\.?|start the conversation\.?|"
    r"this page isn.t available right now|this may be because of a technical error.*|"
    r"scan the qr code.*|[A-Z0-9]{3}-[A-Z0-9]{3}-[A-Z0-9]{3,4}|consumer health privacy|"
    r"contact uploading & non-users|down chevron icon|contact and basic info ?page transparency|"
    r"the number of followers includes all followers.*|you.ll see names and profile pictures.*|"
    r".*'s (photos|reels|follower list is private)|privacy .* meta © \d{4}|© \d{4} instagram from meta|"
    r"meta © \d{4})$",
    re.I)


SOCIAL_CLUTTER_ANYWHERE = re.compile(r"\bfollowers\b.*\bfollowing\b|Afrikaans|Bahasa Indonesia", re.I)


def own_page(url, profile):
    """Whether a link is one of the company's own Facebook/Instagram pages worth fetching: under the page's own
    address, or (Facebook) one of its posts."""
    path = page_path(url)
    if "facebook" in site_domain(url) and FACEBOOK_POST.match(path):
        return True
    return path.lower().startswith(profile.lower()) and not NOT_OWN_PAGE.search(path)


async def profile_home(crawler, config, home, home_url, fetched_by, profile):
    """Where we landed on Facebook/Instagram: (home result, [stored page], problem). problem is None when it is the
    company's own page (profile), or what fetch_site returns instead of pages: a log-in wall, no company page at all,
    or a deleted page."""
    pages = [stored_page(home, home_url, 0, fetched_by)]
    if LOGIN_WALL.match(urlparse(home_url).path):
        return home, pages, {"error": "Facebook/Instagram asked us to log in", "refused": "login_wall"}
    if not profile:
        return home, pages, {"error": "the site sends visitors to Facebook/Instagram, but not to a company page",
                             "placeholder": "social_page_gone"}
    if PAGE_GONE_SOCIAL.search(pages[0]["text"]):
        return home, pages, {"error": "the Facebook/Instagram page is deleted or private",
                             "placeholder": "social_page_gone"}
    if PAGE_UNAVAILABLE.search(pages[0]["text"]):
        for again_url in (home_url, home_url + ("&" if "?" in home_url else "?") + "locale=en_US"):
            await asyncio.sleep(3)
            again = await crawler.arun(again_url, config=config)
            if again.success and not PAGE_UNAVAILABLE.search(again.markdown.raw_markdown if again.markdown else ""):
                return again, [stored_page(again, home_url, 0, fetched_by)], None
    return home, pages, None


def profile_links(links, home_url, profile, seen):
    """The links worth following from the company's page: its own pages and posts, its About page first."""
    links = [link for link in links if own_page(link[0], profile)]
    if "facebook" in site_domain(home_url) and not profile.startswith("/profile.php"):  # a numbered page's About
        parts = urlparse(home_url)                                                      # comes back empty
        about = urlunparse(parts._replace(path=parts.path.rstrip("/") + "/about", query=""))
        if page_path(about).lower() not in seen:
            seen.add(page_path(about).lower())
            links.insert(0, (about, "About"))
    return links


def without_social_clutter(text):
    """A Facebook/Instagram page's text without menus, sign-up prompts and other site furniture."""
    kept = []
    for line in text.splitlines():
        bare = re.sub(r"^[\s#*>|-]+|[\s*|·]+$", "", line).replace("**", "").strip()  # bullets, trailing "·"
        if bare and not SOCIAL_CLUTTER.fullmatch(bare) and not SOCIAL_CLUTTER_ANYWHERE.search(bare):
            kept.append(bare)
    return "\n".join(kept)


def tidy_profile_pages(pages):
    """The company's own words only, and only pages that still say something."""
    for page in pages:
        page["text"] = without_social_clutter(page["text"])
    return [page for page in pages if page["depth"] == 0 or len(page["text"].split()) >= 5]


# ====================================================================================================================
# 4. Fetching one website
# ====================================================================================================================
def seconds_per_page(settings, browser, hard):
    return settings["browser_page_timeout_s"] * (2 if hard else 1) if browser else settings["http_timeout_s"]


def how_to_fetch(settings, browser, hard=False):
    """Crawl4AI's settings for each page. Nothing is cut from a page: headers and footers carry taglines, service
    menus and licence numbers. The browser behaves like an ordinary visitor and waits out bot checks."""
    browser_only = dict(simulate_user=True, override_navigator=True, magic=True,
                        wait_for=BOT_CHECK_CLEARED,
                        wait_for_timeout=settings["challenge_wait_s"] * (2 if hard else 1) * 1000,
                        delay_before_return_html=2.0 if hard else 1.0) if browser else {}
    return CrawlerRunConfig(markdown_generator=DefaultMarkdownGenerator(options={"ignore_links": True,
                                                                                 "ignore_images": True}),
                            page_timeout=seconds_per_page(settings, browser, hard) * 1000, verbose=False,
                            **browser_only)


def nothing_fetched(error=None):
    """What fetch_site returns; every field starts empty."""
    return {"pages": [], "error": error, "refused": None, "domain_not_found": False, "final_url": None,
            "out_of_time": False, "pages_failed": 0, "parked": None, "placeholder": None, "bot_checks": 0}


async def fetch_home_page(crawler, config, url):
    """The home page. If an address won't connect, the other forms of it are tried (with or without www, http).
    Returns (the page or None, the failed attempts)."""
    failed = []
    for address in home_page_addresses(url):
        result = await crawler.arun(address, config=config)
        if result.success:
            return result, failed
        failed.append(result)
        if not TRY_OTHER_ADDRESS.search(str(result.error_message)):
            break  # refused (403 and the like): another form of the address won't help
    return None, failed


def why_home_page_failed(failed, every_address_tried):
    """What the failed attempts tell us. Even a refused page can show that the domain is parked, or a placeholder
    behind an error ('under construction' served with a 503)."""
    errors = [str(attempt.error_message or "failed") for attempt in failed]
    found = {"error": (errors[0] if errors else "failed")[:300], "refused": None, "parked": None,
             "placeholder": None,
             "domain_not_found": every_address_tried and all(DOMAIN_NOT_FOUND.search(e) for e in errors)}
    for attempt, error in zip(failed, errors):
        visible_text = re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", attempt.html or "", flags=re.S | re.I)
        found["refused"] = found["refused"] or refusal_reason(error)
        found["parked"] = found["parked"] or parked_reason(getattr(attempt, "redirected_url", None),
                                                                   html=attempt.html)
        found["placeholder"] = found["placeholder"] or placeholder_reason([{"title": "", "text": visible_text}])
    return found


async def fetch_site(crawler, settings, url, browser, deadline, hard=False, gentle=False):
    """Fetch one website: the home page, then its other pages, most useful first, until the page limit, the
    deadline (time.monotonic()) or several pages in a row that time out. Returns nothing_fetched()'s fields."""
    got = nothing_fetched()
    config, fetched_by = how_to_fetch(settings, browser, hard), "browser" if browser else "http"
    page_limit = settings["max_pages_browser"] if browser else settings["max_pages"]
    at_once = settings["browser_pages_at_once"] if browser else settings["pages_at_once"]
    if gentle:  # a bot check stopped us here last time: browse like one visitor, one page at a time
        at_once = 1

    # 1. The home page, and what kind of place we landed on
    home, failed = await fetch_home_page(crawler, config, url)
    if home is None:
        return {**got, **why_home_page_failed(failed, len(failed) == len(home_page_addresses(url)))}
    home_url = getattr(home, "redirected_url", None) or home.url
    got["final_url"] = home_url
    if is_ad_redirect(home.html):
        got["parked"] = "ad_redirect"
        return got
    profile = social_profile(home_url) or social_profile(url)  # a company's own Facebook/Instagram page
    if profile or on_domain(urlparse(home_url).netloc, PROFILE_SITES):  # on Facebook/Instagram: section 3
        home, pages, problem = await profile_home(crawler, config, home, home_url, fetched_by, profile)
        if problem:
            return {**got, **problem}
        page_limit = min(page_limit, MAX_PROFILE_PAGES)
    else:
        pages = [stored_page(home, home_url, 0, fetched_by)]
    if browser and is_bot_check(pages[0]):
        await asyncio.sleep(settings["bot_check_wait_s"])  # many bot checks clear by themselves after a few seconds
        again = await crawler.arun(home_url, config=config)
        if again.success:
            home, pages = again, [stored_page(again, home_url, 0, fetched_by)]
    if is_bot_check(pages[0]):
        return {**got, "pages": pages, "error": "bot check page", "refused": "bot_check_page"}

    # 2. The other pages, in rounds. `waiting` holds the links found but not fetched yet, each as (address, link
    # text, depth = links away from the home page, the order it was found). Each round: sort the waiting links,
    # most useful first; fetch the next few at once; add the links found on those pages; repeat until the page
    # limit, the time limit, or nothing is left. Rounds are small (3 x the pages fetched at once) so a useful link
    # found on page 3 can still beat a weak one found on the home page.
    domain = site_domain(home_url)
    seen = {page_path(home_url).lower(), page_path(url).lower(), "/index.php", "/index.html", "/index.htm", "/home"}
    links = links_on_page(home, domain, seen)
    if profile:  # no sitemap: it would be the whole of Facebook
        links = profile_links(links, home_url, profile, seen)
    else:
        links += await asyncio.to_thread(links_in_sitemap, home_url, domain, seen)
    waiting = [(link, text, 1, n) for n, (link, text) in enumerate(links)]
    found_so_far, taken_from_group, timeouts_in_a_row = len(waiting), {}, 0
    slots, one_by_one, slowed_down = asyncio.Semaphore(at_once), asyncio.Lock(), []
    bot_checked = []  # inner pages refused by a bot check ("Just a moment...", a Cloudflare challenge)

    async def fetch_page(link):
        """Fetch one page. At most `at_once` pages of the site are fetched at the same time (the `slots`). If the
        site answers "too many requests" (HTTP 429), the whole site slows down from then on: one page at a time
        (`one_by_one`), with a pause of 5, then 10, then 15 seconds, and the page is tried up to 3 times."""
        async with slots:
            result = None
            if gentle:
                await asyncio.sleep(GENTLE_PAUSE_SECONDS)
            for attempt in range(3):
                if time.monotonic() >= deadline:
                    return link, result
                if slowed_down:
                    async with one_by_one:
                        await asyncio.sleep(SLOW_DOWN_SECONDS * (attempt + 1))
                        result = await crawler.arun(link, config=config)
                else:
                    result = await crawler.arun(link, config=config)
                if result.success or "HTTP 429" not in str(result.error_message):
                    return link, result
                slowed_down.append(link)
            return link, result

    while waiting and len(pages) < page_limit:
        if time.monotonic() >= deadline or timeouts_in_a_row >= settings["stop_after_timeouts"]:
            got["out_of_time"] = True
            break
        # Most useful first: page_rules' rank, then how clearly the link names one of our segments, then the nearest
        # to the home page, then the order found. Small rounds, so links found on new pages can move up.
        waiting.sort(key=lambda w: (page_rules.tier(w[0], w[1], taken_from_group),
                                    -page_rules.segment_score(w[0], w[1]), w[2], w[3]))
        take = min(at_once * 3, page_limit - len(pages))
        batch, waiting = waiting[:take], waiting[take:]
        for link, *_ in batch:
            group = page_rules.group(link)
            if group:
                taken_from_group[group] = taken_from_group.get(group, 0) + 1
        depth_of = {link: depth for link, _, depth, _ in batch}
        for link, result in await asyncio.gather(*(fetch_page(link) for link, *_ in batch)):
            if result is None:  # the time ran out before this page started
                got["out_of_time"] = True
                continue
            timed_out = not result.success and unreachable_reason(str(result.error_message)) == "timeout"
            timeouts_in_a_row = timeouts_in_a_row + 1 if timed_out else 0
            if not result.success:
                if refusal_reason(str(result.error_message)):  # refused: a bot check (Cloudflare, ...) or a 403
                    bot_checked.append(link)
                elif not PAGE_GONE.search(str(result.error_message)):  # a dead link on their site isn't our failure
                    got["pages_failed"] += 1
                continue
            landed = getattr(result, "redirected_url", None) or link
            if profile and not own_page(landed, profile):  # Facebook sent us off the company's page (to Meta's own
                continue                                   # About page, a log-in page): not the company's, not kept
            page = stored_page(result, link, depth_of[link], fetched_by)
            if is_bot_check(page):
                bot_checked.append(link)
                continue
            pages.append(page)
            if depth_of[link] < settings["max_depth"]:
                for new_link, text in links_on_page(result, domain, seen):
                    if profile and not own_page(new_link, profile):
                        continue
                    waiting.append((new_link, text, depth_of[link] + 1, found_so_far))
                    found_so_far += 1
        if bot_checked:  # the home page got through but the other pages are being refused: stop here, keep what we
            break        # have, and label it "partial_bot_check"; the next run tries again, gently
    got["bot_checks"] = len(bot_checked)
    got["pages"] = without_repeats(tidy_profile_pages(pages) if profile else pages)
    return got


async def fetch_site_in_time(crawler, settings, url, browser, hard=False, gentle=False):
    """fetch_site within the site's time limit (doubled on the last pass). If a single page hangs past its own
    timeout, the site gives up with nothing."""
    limit = settings["site_timeout"] * (2 if hard else 1)
    try:
        return await asyncio.wait_for(fetch_site(crawler, settings, url, browser, time.monotonic() + limit, hard,
                                                 gentle),
                                      timeout=limit + seconds_per_page(settings, browser, hard) + 30)
    except asyncio.TimeoutError:
        return nothing_fetched("a page hung past its timeout")
    except Exception as err:  # noqa: BLE001 (any crawler error ends this site, not the run)
        return nothing_fetched(str(err)[:200])


# ====================================================================================================================
# 5. What did we get?  Each pass ends a site with a status, or hands it on to the next pass.
# ====================================================================================================================
def site_result(status, reason, pages=(), error=None):
    return {"status": status, "reason": reason, "pages": list(pages), "error": error}


def ok_reason(got, thin=False):
    """'partial_bot_check' when bot checks kept us from some pages; otherwise 'thin' for one short page, 'partial'
    when time ran out or more pages failed than were fetched, else 'complete'."""
    if got.get("bot_checks"):
        return "partial_bot_check"
    if thin:
        return "thin"
    return "partial" if got["out_of_time"] or got["pages_failed"] > len(got["pages"]) else "complete"


async def judge_plain_download(url, got, settings):
    """Pass 1's verdict. Checked in this order, and the first that applies decides:
      1. the domain doesn't exist                        -> dead_site
      2. our own network filter answered                 -> network_blocked
      3. a failed attempt showed parking                 -> parked
      4. a failed attempt showed a placeholder, no pages -> dead_site
      5. pages came back and nothing refused us: parked page -> parked; host error page -> dead_site or
         unreachable; placeholder -> dead_site; more than one page, or one page with 150+ words -> ok
      6. the home page itself is gone (404)              -> dead_site
      7. a plain request (following redirects) shows parking -> parked
    None of these: it refused us, failed, or gave one thin page, so it is handed to the browser (returns None)."""
    pages = got["pages"]
    if got["domain_not_found"]:
        return site_result("dead_site", "dns_not_found", error="the domain doesn't exist (with or without www)")
    if stopped_by_our_filter(got["final_url"], pages):
        return site_result("network_blocked", "web_filter", error=FILTER_MESSAGE)
    if got["parked"]:
        return site_result("parked", got["parked"], error="parked or for-sale domain")
    if got["placeholder"] and not pages:
        return site_result("dead_site", got["placeholder"], error=got["error"])
    if pages and not got["refused"]:
        parked = parked_reason(got["final_url"], pages)
        if parked:
            return site_result("parked", parked, pages)
        host_error = host_error_status(pages)
        if host_error:
            return site_result(*host_error, error=f"a host or CDN error page: {pages[0]['title']}")
        placeholder = placeholder_reason(pages)
        if placeholder:
            return site_result("dead_site", placeholder, pages)
        if len(pages) > 1 or words(pages) >= settings["thin_words"]:  # a real, if small, website
            return site_result("ok", ok_reason(got), pages)
    if not pages and PAGE_GONE.search(got["error"] or ""):
        return site_result("dead_site", "http_404", error=got["error"])
    parked = await asyncio.to_thread(parked_by_plain_request, url)
    if parked:
        return site_result("parked", parked, error="parked or for-sale domain")
    return None  # refused, failed, or one thin page: try the browser


def judge_browser(got, plain, settings, last_try):
    """Pass 2's (and pass 3's) verdict. plain = what pass 1 got. In this order, the first that applies decides:
      1. our network filter, parking, a placeholder with no pages, a host error page -> as in pass 1
      2. the browser got pages and wasn't refused: a placeholder -> dead_site; at least as many words as pass 1
         (and at least 20) -> ok ("thin" when it is one page under 150 words)
      3. pass 1 got a short page and the browser found nothing more -> ok, "thin", with pass 1's page
      4. refused or timed out, and this isn't the last pass -> None: try once more with the undetected browser
      5. refused on the last pass -> blocked; anything else -> unreachable"""
    plain_pages = plain["pages"] if not plain["refused"] else []
    if stopped_by_our_filter(got["final_url"], got["pages"]):
        return site_result("network_blocked", "web_filter", error=FILTER_MESSAGE)
    parked = got["parked"] or parked_reason(got["final_url"], got["pages"])
    if parked:
        return site_result("parked", parked, got["pages"], error="parked or for-sale domain")
    if got["placeholder"] and not got["pages"]:
        return site_result("dead_site", got["placeholder"], error=got["error"])
    host_error = host_error_status(got["pages"]) or host_error_status(plain_pages)
    if host_error:
        title = (got["pages"] or plain_pages)[0]["title"]
        return site_result(*host_error, error=f"a host or CDN error page: {title}")
    if got["pages"] and not got["refused"]:
        placeholder = placeholder_reason(got["pages"])
        if placeholder:
            return site_result("dead_site", placeholder, got["pages"])
        if words(got["pages"]) >= max(words(plain_pages), NEARLY_EMPTY):  # the browser got more
            thin = len(got["pages"]) == 1 and words(got["pages"]) < settings["thin_words"]
            return site_result("ok", ok_reason(got, thin), got["pages"])
    if words(plain_pages) >= NEARLY_EMPTY:  # one short page, and the browser found nothing more
        return site_result("ok", "thin", plain_pages)
    if not last_try and (got["refused"] or unreachable_reason(got["error"]) == "timeout"):
        return None  # refused, or timed out: one more try with the undetected browser
    if got["refused"]:
        return site_result("blocked", got["refused"],
                           error=f"refused by the site (plain download and browser): {got['error']}"[:300])
    errors = f"{plain['error']} | browser: {got['error']}"
    if got["pages"] or plain_pages or "Near-empty" in errors:  # a page came back, with next to no text
        return site_result("unreachable", "empty_page", error=errors[:300])
    return site_result("unreachable", unreachable_reason(got["error"] or plain["error"]), error=errors[:300])


# ====================================================================================================================
# 6. The browsers
# ====================================================================================================================
_chrome_user_agent = None


async def chrome_user_agent():
    """The installed Chrome's own user agent (without 'Headless'). Crawl4AI's default one is years old, and some
    site firewalls refuse it."""
    global _chrome_user_agent
    if _chrome_user_agent is None:
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                _chrome_user_agent = (await page.evaluate("navigator.userAgent")).replace("HeadlessChrome", "Chrome")
                await browser.close()
        except Exception:  # noqa: BLE001
            _chrome_user_agent = CHROME
    return _chrome_user_agent


class Browser:
    """One browser per worker process, restarted with a fresh profile every few dozen sites (memory). Pass 2 uses
    a hidden Chrome with Crawl4AI's stealth settings; pass 3 (hard) Crawl4AI's undetected browser in a visible
    window. A profile lasts while the browser runs, so a bot check passed once covers the site's other pages."""

    def __init__(self, restart_every, hard=False):
        self.crawler, self.sites_done, self.restart_every, self.hard, self.profile = None, 0, restart_every, hard, None

    async def fetch(self, settings, url, gentle=False):
        if self.crawler is None or self.sites_done >= self.restart_every:
            await self.close()
            self.profile = tempfile.mkdtemp(prefix="crawl_profile_")
            config = BrowserConfig(enable_stealth=True, headless=not self.hard, verbose=False, headers={},
                                   user_agent=await chrome_user_agent(), use_persistent_context=True,
                                   user_data_dir=self.profile)
            if self.hard:
                strategy = AsyncPlaywrightCrawlerStrategy(browser_config=config, browser_adapter=UndetectedAdapter())
                self.crawler = AsyncWebCrawler(crawler_strategy=strategy, config=config)
            else:
                self.crawler = AsyncWebCrawler(config=config)
            await self.crawler.start()
            self.sites_done = 0
        self.sites_done += 1
        return await fetch_site_in_time(self.crawler, settings, url, browser=True, hard=self.hard, gentle=gentle)

    async def close(self):
        if self.crawler is not None:
            try:
                await self.crawler.close()
            except Exception:  # noqa: BLE001 (already gone)
                pass
            self.crawler = None
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = None


# ====================================================================================================================
# 7. The passes
# ====================================================================================================================
async def plain_download_pass(settings, sites, results_file):
    """Pass 1: several sites at once through one plain-download client."""
    client = AsyncWebCrawler(crawler_strategy=AsyncHTTPCrawlerStrategy(
        browser_config=HTTPCrawlerConfig(verify_ssl=False,  # many small-business certificates have expired
                                         headers={"User-Agent": CHROME}),
        max_connections=settings["http_sites_per_worker"] * settings["pages_at_once"] * 2))
    await client.start()
    sites_at_once = asyncio.Semaphore(settings["http_sites_per_worker"])

    async def one_site(site):
        async with sites_at_once:
            start = time.perf_counter()
            got = await fetch_site_in_time(client, settings, site["url"], browser=False, gentle=site.get("gentle"))
            verdict = await judge_plain_download(site["url"], got, settings)
        seconds = round(time.perf_counter() - start, 1)
        if verdict:
            append_line(results_file, {**site, **verdict, "seconds": seconds})
        else:  # handed to the browser, with what pass 1 got
            append_line(results_file, {**site, "status": "needs_browser", "plain": got, "seconds": seconds})

    try:
        await asyncio.gather(*(one_site(site) for site in sites))
    finally:
        await client.close()


async def browser_pass(settings, sites, results_file, hard=False):
    """Passes 2 and 3: one site at a time (more browsers means more worker processes)."""
    browser = Browser(settings["restart_browser_every"], hard)
    try:
        for site in sites:
            start = time.perf_counter()
            plain = site.pop("plain")
            got = await browser.fetch(settings, site["url"], gentle=site.get("gentle"))
            verdict = judge_browser(got, plain, settings, last_try=hard)
            seconds = round(site.pop("seconds") + time.perf_counter() - start, 1)
            if verdict:
                append_line(results_file, {**site, **verdict, "seconds": seconds})
            else:  # handed to pass 3
                append_line(results_file, {**site, "status": "needs_retry_pass", "plain": plain, "seconds": seconds})
    finally:
        await browser.close()


async def main(job_file, results_file):
    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    if job["mode"] == "http":
        await plain_download_pass(job["settings"], job["sites"], results_file)
    else:
        await browser_pass(job["settings"], job["sites"], results_file, hard=job["mode"] == "browser_hard")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
