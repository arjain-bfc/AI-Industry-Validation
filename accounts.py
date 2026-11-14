"""The accounts as the pipeline reads them from an input file, and which of their links are worth crawling.

  load_accounts()     one tidy row per account: account_id in lower case, the website as a full address
  load_contacts()     each account's CRM phone, email and DBA (used to confirm a website is the company's)
  site_key()          a web address compared loosely, so 'https://www.Acme.com/' and 'http://acme.com' match
  same_company_key()  accounts with the same website, name and DBA are one company entered more than once
  is_listing_link()   a link that isn't a company website (social media, a directory, a marketplace): not crawled
  social_profile()    a company's own Facebook or Instagram page, the one kind of social link that is crawled
"""
import re
from urllib.parse import parse_qsl, urlparse

import pandas as pd


def load_accounts(source):
    """The accounts, tidied: one row per account (indexed by its row number in the file, as Excel counts it),
    account_id in lower case, the website with https:// in front. source: an Excel file, or a table already read
    (data_warehouse.accounts)."""
    df = (source.copy() if isinstance(source, pd.DataFrame) else pd.read_excel(source, dtype=str)).fillna("")
    # Line breaks inside cells (addresses), stray carriage returns and the text "NULL" for empty cells
    df = df.replace({r"_x000D_": "", r"\s*\n\s*": ", ", r"^\s*NULL\s*$": ""}, regex=True)
    df = df.apply(lambda column: column.str.strip())
    df.index = pd.RangeIndex(len(df)) + 2  # row numbers as Excel counts them: the header is row 1
    df["account_id"] = df["account_id"].str.lower()
    df = df[(df["account_id"] != "") & ~df["account_id"].duplicated()]
    df["url"] = df["company_website"].map(full_address)
    return df


def full_address(website):
    """'acme.com' -> 'https://acme.com'; an empty cell -> None."""
    if not website:
        return None
    return website if website.startswith("http") else "https://" + website


def site_key(url):
    """A web address compared loosely: 'https://www.Acme.com/' and 'http://acme.com' are the same site."""
    if not url:
        return ""
    parts = urlparse(url.lower())
    return parts.netloc.removeprefix("www.") + parts.path.rstrip("/") + (f"?{parts.query}" if parts.query else "")


# --- The same company entered twice --------------------------------------------------------------------------------
# Accounts with the same web address AND the same name (and DBA) are the same company entered more than once in the
# CRM: they share one model call, so they always get the same answer. Names must be identical once case, punctuation
# and legal endings are ignored; anything less gets its own call (a wrong match would copy one company's answer to
# another, a missed one only costs a call).
LEGAL_ENDINGS = re.compile(r"\b(inc|incorporated|llc|l l c|ltd|limited|co|corp|corporation|company|the|lp|llp|"
                           r"pllc|pc)\b")


def clean_name(name):
    """'Acme Utilities, Inc.' -> 'acme utilities'."""
    return " ".join(LEGAL_ENDINGS.sub(" ", re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())).split())


def same_company_key(url, name, dba=""):
    """Accounts with the same key are the same company: same web address, same name, same DBA."""
    return site_key(url), clean_name(name), clean_name(dba)


def load_contacts(input_xlsx):
    """{account_id: {"phone", "email", "dba"}} from the input Excel."""
    df = pd.read_excel(input_xlsx, dtype=str).fillna("")
    contacts = {}
    for row in df.itertuples():
        if row.account_id.strip():
            contacts[row.account_id.strip().lower()] = {"phone": row.phone_number.strip(),
                                                        "email": row.email_address.strip().lower(),
                                                        "dba": row.doing_business_as.strip()}
    return contacts


# --- Links that aren't a company website ------------------------------------------------------------------------------
# Not every link in the CRM is a company's website. Links to social media, directories, review sites and marketplaces
# are pages about the company on someone else's site: they aren't crawled. A company's own Facebook or Instagram page
# is the exception: it is crawled, narrowly (crawl_worker.py, section 3). Any other link goes on to Phase 2, whose
# website check judges whether the site is really the company's.
# Pages about a company on someone else's site: not crawled (the account is stored as "social_media_page_only", a
# name kept from when the list had only social media). Found in the CRM and ZoomInfo exports or common enough to
# expect. A link not listed here goes on to Phase 2, whose website check judges it.
LISTING_SITES = (
    # social media and link-in-bio pages
    "facebook.com", "fb.com", "fb.me", "instagram.com", "linkedin.com", "x.com", "twitter.com", "youtube.com",
    "youtu.be", "tiktok.com", "pinterest.com", "threads.net", "nextdoor.com", "linktr.ee", "beacons.ai", "bio.link",
    "linkin.bio",
    # Google (log-in, Maps and business-profile links) and other maps
    "google.com", "g.page", "goo.gl", "maps.apple.com", "bing.com", "waze.com",
    # directories, review and lead-generation sites
    "yelp.com", "bbb.org", "yellowpages.com", "superpages.com", "whitepages.com", "manta.com", "angi.com",
    "angieslist.com", "homeadvisor.com", "thumbtack.com", "houzz.com", "porch.com", "bark.com", "networx.com",
    "fixr.com", "buildzoom.com", "expertise.com", "birdeye.com", "alignable.com", "mapquest.com", "ezlocal.com",
    "trady.com", "chamberofcommerce.com", "merchantcircle.com", "citysquares.com", "dexknows.com", "local.com",
    "hotfrog.com", "brownbook.net", "cylex.us.com", "cylex-usa.com", "showmelocal.com", "nicelocal.com",
    # company-data sites
    "bizapedia.com", "opencorporates.com", "dnb.com", "zoominfo.com", "buzzfile.com", "crunchbase.com",
    # found in the CRM export: one portal standing in for dozens of unrelated companies' websites
    "septic.com", "towing.com", "car-part.com", "mobiletruckrepair.info", "truckrepairdirectory.com",
    "landscapeservice.us", "localtreecompany.com", "locallawnmaintenance.com", "relevantyellow.com",
    # marketplaces
    "etsy.com", "amazon.com", "ebay.com",
)


WEBSITE_BUILDERS = ("sites.google.com",)  # under a listed domain, but the company's own site


# Except a company's own Facebook or Instagram page: logged out, it still shows the company's intro and category
# (Facebook) or bio and post captions (Instagram). crawl_worker.py fetches just that page, its About page and its own
# posts. The other sites above gave nothing about the company (sign-up walls, their own menus, bot checks).
PROFILE_SITES = ("facebook.com", "fb.com", "instagram.com")


NOT_A_PROFILE = re.compile(r"^/(login|sharer|share|help|policies|business|reg|recover|pages/creation|watch|marketplace|"
                           r"groups|events|gaming|explore|accounts|direct|stories|about|privacy|legal|photo|search|"
                           r"home\.php|l\.php|p\.php|tr)(/|\.php|$)", re.I)  # Facebook's own pages, not a company's


def on_domain(host, domains):
    """'www.yelp.com' is on 'yelp.com'; so is 'm.yelp.com'."""
    host = host.lower().split(":")[0].removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in domains)


def social_profile(url):
    """For a company's own Facebook or Instagram page, the start of its addresses ('/acmetowing',
    '/profile.php?id=123', '/p/Acme-Towing-123'); None for anything else."""
    parts = urlparse(url or "")
    if not on_domain(parts.netloc, PROFILE_SITES):
        return None
    path = parts.path.rstrip("/")
    if path.lower() == "/profile.php":
        page_id = dict(parse_qsl(parts.query)).get("id")
        return f"/profile.php?id={page_id}" if page_id else None
    steps = [step for step in path.split("/") if step]
    if not steps or NOT_A_PROFILE.match(path):
        return None
    if steps[0].lower() in ("p", "people", "pages"):  # /p/Name-123, /people/Name/123, /pages/category/X/Name-123
        return path
    return "/" + steps[0]


def is_listing_link(url):
    """A link to a page about the company on someone else's site (LISTING_SITES): not crawled. A company's own
    Facebook or Instagram page and a site built with a listed website builder are crawled."""
    host = urlparse(url or "").netloc
    if on_domain(host, WEBSITE_BUILDERS) or social_profile(url):
        return False
    return on_domain(host, LISTING_SITES)
