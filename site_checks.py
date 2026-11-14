"""Is it a real business website? And if a fetch failed, why?

The crawler (crawl_worker.py) asks these questions about what came back from a site. A site that isn't a real
business website ends with one of these statuses:
  parked           the domain is parked or for sale
  dead_site        the domain doesn't exist any more, or shows only a placeholder or a host's error page, or
                   the Facebook/Instagram page is deleted or shown to friends only
  blocked          the site refused us (bot protection, 403, 429, a Facebook/Instagram log-in wall, ...)
  network_blocked  our own network's web filter stopped the request (we never reached the site)
  unreachable      no answer, or an error that may be temporary (tried again on a later run)
Every pattern here was added for sites we actually met. Pages that slip past these checks (an unusual error page, a
placeholder with a lot of text) are caught later by Phase 2's website check.

How to read the patterns (regular expressions): see the top of crawl_worker.py.
"""
import re
from urllib.parse import urlparse

import requests

from accounts import on_domain


def words(pages):
    """Total words across the pages."""
    return sum(len(p["text"].split()) for p in pages)


def first_text(pages, chars=600):
    """Each page's title and the start of its text, joined: enough to recognise a placeholder or parked page."""
    return " ".join(f"{p['title'] or ''} {p['text'][:chars]}" for p in pages)


# --- Bot checks ---------------------------------------------------------------------------------------------------
# "Checking your browser" pages put up by bot protection instead of the site. Catches, for example:
#   Cloudflare's "Just a moment..." and "Attention required", "Checking your browser before accessing ...",
#   "Verify you are human", "Please complete the captcha to continue", "DDoS protection by ...".
# "captcha" on its own isn't enough: many contact forms say "protected by reCAPTCHA".
BOT_CHECK = re.compile(r"checking your browser|confirm you are human|verify you are human|are you a robot|"
                       r"just a moment\.\.\.|attention required|access denied|(complete|solve) the captcha|"
                       r"captcha (to continue|required)|ddos protection|security check", re.I)


def is_bot_check(page):
    """A short page that is only a 'checking your browser' screen."""
    return len(page["text"].split()) < 300 and bool(BOT_CHECK.search(f"{page['title'] or ''} {page['text'][:500]}"))


# --- Parked and for-sale domains -------------------------------------------------------------------------------------
# Domain marketplaces that parked and for-sale domains forward to
PARKING_HOSTS = ("forsale.godaddy.com", "afternic.com", "sedo.com", "dan.com", "hugedomains.com", "undeveloped.com",
                 "bodis.com", "parkingcrew.net", "above.com", "sav.com", "domainmarket.com", "brandbucket.com")


# What a parked page says about itself: "This domain is parked free", "The domain name may be for sale", "Buy this
# domain", "This domain has expired". (Ads and "related searches" can make a parked page long, so length alone
# doesn't tell.)
PARKED_WORDS = re.compile(r"is parked|parked free|domain (name )?(is |may be )?for sale|buy this domain|"
                          r"domain parking|this domain (has expired|is available)", re.I)


# GoDaddy-style parking: the home page is only a line of code, location.href = "/lander", that sends the visitor
# to a for-sale page. The pattern finds that line (\s* allows spaces around the =).
LANDER_SCRIPT = re.compile(r"""location\.href\s*=\s*["']/lander""", re.I)


# Ad networks' "Redirecting..." pages: a page titled "Redirecting" that is made of ad scripts (Google ad tags and
# the like)
AD_REDIRECT_TITLE = re.compile(r"<title>\s*Redirecting", re.I)


AD_SCRIPTS = re.compile(r"prebid|dfp-ad|googlesyndication|adsbygoogle|ad-overlay", re.I)


def is_ad_redirect(html):
    html = html or ""
    return len(html) < 20000 and bool(AD_REDIRECT_TITLE.search(html)) and bool(AD_SCRIPTS.search(html))


def parked_reason(final_url, pages=(), html=""):
    """Why this looks parked ('for_sale_page', 'registrar_lander', 'parked_page', 'ad_redirect'), or None."""
    if on_domain(urlparse(final_url or "").netloc, PARKING_HOSTS):
        return "for_sale_page"
    if urlparse(final_url or "").path.lower().startswith("/lander"):
        return "registrar_lander"
    if html and len(html) < 2000 and LANDER_SCRIPT.search(html):
        return "registrar_lander"
    if html and is_ad_redirect(html):
        return "ad_redirect"
    if pages and words(pages) < 400 and PARKED_WORDS.search(first_text(pages)):
        return "parked_page"
    return None


def parked_by_plain_request(url):
    """Ask for the home page with a plain request that follows redirects. This catches parking the crawler can't
    see: the /lander script page looks empty to it, and for-sale pages often refuse crawlers. Tried twice."""
    for _ in range(2):
        try:
            resp = requests.get(url, timeout=(5, 10))
        except requests.RequestException:
            continue
        return parked_reason(resp.url, html=resp.text)
    return None


# --- Placeholders and host error pages -------------------------------------------------------------------------------
# Short pages (under 60 words) that say nothing about the business. Checked in this order; the first match wins:
#   http_404     "404", "Page not found"           (\b404\b: 404 as a number on its own, not inside 14045)
#   coming_soon  "Coming soon", "Under construction", the Chinese 建设中 and Spanish "en construcción"
#   suspended    "Account suspended", "Website disabled", a closed web shop ("This store is unavailable")
PLACEHOLDERS = [
    ("http_404", re.compile(r"\b404\b|not found", re.I)),
    ("coming_soon", re.compile(r"coming soon|under construction|建设中|en construcci[oó]n", re.I)),
    ("suspended", re.compile(r"website disabled|site disabled|account suspended|site suspended|"
                             r"this store is unavailable|store is currently unavailable", re.I)),  # closed web shops
]


# A web host's or CDN's own error page shown instead of the site.
# Gone (not set up anywhere; the site is dead):
#   Cloudflare "Error 1001: DNS resolution error" (also 1014, 1016), "domain not configured", "Site not found",
#   Heroku "No such app", GitHub "There isn't a GitHub Pages site here"
# Down (may be temporary, so tried again on a later run):
#   Cloudflare "Error 521: Web server is down" (520 to 527), "502 Bad Gateway", "504 Gateway Timeout", "Temporarily
#   unavailable", and a web server's own default page ("Welcome to nginx!", the Apache or IIS test page), which
#   means the server is up but the site isn't on it
HOST_SAYS_GONE = re.compile(r"DNS resolution error|Error 10(01|14|16)\b|Origin DNS error|domain (is )?not configured|"
                            r"site not found|no such app|there isn.t a github pages site here", re.I)


HOST_SAYS_DOWN = re.compile(r"Error 52[0-7]\b|web server is down|origin is unreachable|a timeout occurred|"
                            r"SSL handshake failed|502 bad gateway|504 gateway time-?out|"
                            r"welcome to nginx|apache2? \w* ?default page|test page for the apache|"  # server's own
                            r"iis windows server|temporarily unavailable|service unavailable", re.I)  # default page


def placeholder_reason(pages):
    """'http_404' / 'coming_soon' / 'suspended' for a short placeholder site, else None."""
    if not pages or words(pages) >= 60:
        return None
    return next((reason for reason, pattern in PLACEHOLDERS if pattern.search(first_text(pages))), None)


def host_error_status(pages):
    """('dead_site' | 'unreachable', 'host_error') when the 'site' is a host or CDN error page, else None."""
    if not pages or words(pages) >= 400:
        return None
    text = first_text(pages, 1500)
    if HOST_SAYS_GONE.search(text):
        return "dead_site", "host_error"
    if HOST_SAYS_DOWN.search(text):
        return "unreachable", "host_error"
    return None


# --- Our own network ---------------------------------------------------------------------------------------------
# Beacon's web filter (Cisco Umbrella / OpenDNS) answers instead of the site; trying again from here can't help.
FILTER_HOSTS = ("opendns.com", "umbrella.com")


FILTER_MESSAGE = "blocked by our own network's web filter (OpenDNS): check the site by hand or ask IT to allow it"


def stopped_by_our_filter(final_url, pages=()):
    return any(on_domain(urlparse(u or "").netloc, FILTER_HOSTS) for u in [final_url, *(p.get("url") for p in pages)])


# --- Fetch errors --------------------------------------------------------------------------------------------------
# The error messages that mean the site refused us, checked in this order (first match wins):
#   bot_check_page  "Wait condition failed": the browser waited for a bot check to clear, and it never did
#   akamai, cloudflare, captcha   the bot protection named in the error
#   http_403, http_429, http_503  "HTTP 403" (forbidden, also 401), "HTTP 429" (too many requests), "HTTP 503"
# Crawl4AI's "Structural" warnings (little text, heavy scripts) are not refusals: the page just needs a browser.
REFUSALS = [
    ("bot_check_page", re.compile(r"Wait condition failed", re.I)),  # the browser's bot check never cleared
    ("akamai", re.compile(r"akamai", re.I)),
    ("cloudflare", re.compile(r"cloudflare|challenge", re.I)),
    ("captcha", re.compile(r"captcha", re.I)),
    ("http_403", re.compile(r"HTTP 40[13]|access denied", re.I)),
    ("http_429", re.compile(r"HTTP 429", re.I)),
    ("http_503", re.compile(r"HTTP 503", re.I)),
]


PAGE_GONE = re.compile(r"HTTP 404|HTTP 410", re.I)  # the page doesn't exist (410: deleted on purpose)


# The domain doesn't exist: the wording Chrome and Python use when a name can't be looked up
DOMAIN_NOT_FOUND = re.compile(r"ERR_NAME_NOT_RESOLVED|getaddrinfo failed|Name or service not known|"
                              r"nodename nor servname|No address associated", re.I)


# Connection problems where another form of the address may work (some sites answer only with or without "www",
# or only over http): name lookup, connection, certificate and time-out errors
TRY_OTHER_ADDRESS = re.compile(r"ERR_NAME|ERR_CONNECTION|ERR_SSL|ERR_CERT|ERR_HTTP2|ERR_TIMED_OUT|ERR_ADDRESS|"
                               r"getaddrinfo|Cannot connect|ClientConnector|SSL|certificate|Server disconnected|"
                               r"timed? ?out|Timeout|nodename|Name or service", re.I)


def refusal_reason(error):
    """Why the site refused us ('akamai', 'http_403', ...), or None when the error isn't a refusal."""
    if not error or "Structural" in error:
        return None
    return next((reason for reason, pattern in REFUSALS if pattern.search(error)), None)


def unreachable_reason(error):
    """'timeout' / 'ssl' / 'connection_failed' / 'other'."""
    error = error or ""
    if re.search(r"timed? ?out|Timeout", error, re.I):
        return "timeout"
    if re.search(r"SSL|certificate", error, re.I):
        return "ssl"
    if re.search(r"ClientConnector|Cannot connect|ERR_CONNECTION|Connection failed|ERR_ADDRESS", error, re.I):
        return "connection_failed"
    return "other"
