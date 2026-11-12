"""Which channel a visit came from, and the lists that decide it.

The lists are data at the top of this file so that adding a search engine or an
AI assistant is a one-line change. The function below them compares parsed
hosts on label boundaries and never searches inside a string: 't.co' is a
social network, and it is also a substring of 'chatgpt.com'.

Nothing here is stored. The channel is worked out when the dashboard is read,
from the referrer and the utm parameters already on each pageview, so a change
to these lists corrects history as well.
"""
import re
from typing import Optional
from urllib.parse import urlsplit

DIRECT = "Direct"
ORGANIC_SEARCH = "Organic Search"
SOCIAL = "Social"
EMAIL = "Email"
PAID = "Paid"
AI_ASSISTANTS = "AI Assistants"
REFERRAL = "Referral"

# A host matches an entry when it is the entry or a subdomain of it.
AI_HOSTS = (
    "chatgpt.com", "chat.openai.com", "openai.com", "claude.ai",
    "perplexity.ai", "gemini.google.com", "bard.google.com",
    "copilot.microsoft.com", "copilot.com", "you.com", "phind.com", "poe.com",
    "deepseek.com", "chat.deepseek.com", "grok.com", "meta.ai",
    "chat.mistral.ai",
)
# utm_source values that are a product name rather than a host.
AI_SOURCE_NAMES = (
    "chatgpt", "openai", "claude", "perplexity", "gemini", "copilot",
    "deepseek", "grok", "poe", "phind", "mistral",
)

SEARCH_HOSTS = (
    "bing.com", "duckduckgo.com", "baidu.com", "ask.com", "ecosia.org",
    "search.brave.com", "brave.com", "startpage.com", "qwant.com", "kagi.com",
    "naver.com", "seznam.cz", "sogou.com", "aol.com", "yahoo.com",
    "search.yahoo.com",
)
# Brands that run one site per country: google.com, google.se, google.co.uk.
SEARCH_BRANDS_ANY_TLD = ("google", "yahoo", "yandex")

SOCIAL_HOSTS = (
    "facebook.com", "fb.com", "fb.me", "twitter.com", "t.co", "x.com",
    "linkedin.com", "lnkd.in", "instagram.com", "reddit.com", "pinterest.com",
    "pin.it", "tiktok.com", "snapchat.com", "youtube.com", "youtu.be",
    "vimeo.com", "threads.net", "bsky.app", "mastodon.social", "tumblr.com",
    "whatsapp.com", "t.me", "telegram.org", "discord.com", "vk.com",
)

PAID_MEDIUMS = ("cpc", "ppc", "paid", "paidsearch", "paid-search", "paid_social", "display")
SOCIAL_MEDIUMS = ("social", "social-media", "social_media", "sm")
EMAIL_MEDIUMS = ("email", "e-mail", "newsletter")
AI_MEDIUMS = ("ai", "llm")

_BRAND_PATTERNS = tuple(
    re.compile(rf"^(?:.+\.)?{brand}\.(?:co\.|com\.)?[a-z]{{2,3}}$")
    for brand in SEARCH_BRANDS_ANY_TLD
)


def host_of(value: Optional[str]) -> Optional[str]:
    """The lowercase host of a URL or bare domain, without www and port.

    None for anything that is not a web address: empty, about://newtab,
    android-app://..., a malformed value.
    """
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        if "://" in value:
            parts = urlsplit(value)
            if parts.scheme.lower() not in ("http", "https"):
                return None
        elif ":" in value.split("/", 1)[0] and not re.match(r"^[^/:]+:\d+(/|$)", value):
            # about:blank, mailto:, javascript: and the like.
            return None
        else:
            parts = urlsplit("//" + value)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    return host


def _matches(host: str, entries) -> bool:
    return any(host == e or host.endswith("." + e) for e in entries)


def is_own_host(host: Optional[str], own_domain: Optional[str]) -> bool:
    """True when host is the site's own domain or one of its subdomains."""
    own = host_of(own_domain)
    return bool(host and own and (host == own or host.endswith("." + own)))


def own_referrer_regex(own_domain: Optional[str]) -> Optional[str]:
    """A PostgreSQL regex matching referrer URLs on the site's own domain.

    The SQL twin of is_own_host, for queries that must leave those rows out.
    None when the domain cannot be parsed, so the caller excludes nothing.
    """
    own = host_of(own_domain)
    if not own or not re.fullmatch(r"[a-z0-9.-]+", own):
        return None
    escaped = own.replace(".", r"\.")
    return rf"^(https?://)?(www\.)?([a-z0-9-]+\.)*{escaped}(:[0-9]+)?([/?#]|$)"


def _source_channel(source: str) -> Optional[str]:
    """Channel for a utm_source value, only where it says something clear."""
    s = source.strip().lower()
    if s in AI_SOURCE_NAMES:
        return AI_ASSISTANTS
    host = host_of(s) if "." in s else None
    if host and _matches(host, AI_HOSTS):
        return AI_ASSISTANTS
    return None


def _host_channel(host: str) -> str:
    if _matches(host, AI_HOSTS):
        return AI_ASSISTANTS
    if _matches(host, SEARCH_HOSTS) or any(p.match(host) for p in _BRAND_PATTERNS):
        return ORGANIC_SEARCH
    if _matches(host, SOCIAL_HOSTS):
        return SOCIAL
    return REFERRAL


def classify_channel(
    referrer: Optional[str],
    utm_medium: Optional[str] = None,
    utm_source: Optional[str] = None,
    own_domain: Optional[str] = None,
) -> str:
    """The traffic channel of one visit.

    Order: an explicit utm_medium of email or paid wins, then an AI assistant
    named in utm_source or utm_medium, then the referrer host, then a social
    medium. A referrer on the site's own domain, or one that is not a web
    address, counts as Direct: the visitor did not arrive from elsewhere.
    """
    medium = (utm_medium or "").strip().lower()
    if medium in EMAIL_MEDIUMS:
        return EMAIL
    if medium in PAID_MEDIUMS:
        return PAID
    if medium in AI_MEDIUMS:
        return AI_ASSISTANTS
    if utm_source and _source_channel(utm_source) == AI_ASSISTANTS:
        return AI_ASSISTANTS

    host = host_of(referrer)
    if host and not is_own_host(host, own_domain):
        channel = _host_channel(host)
        if channel != REFERRAL:
            return channel
        if medium in SOCIAL_MEDIUMS:
            return SOCIAL
        return REFERRAL
    if medium in SOCIAL_MEDIUMS:
        return SOCIAL
    return DIRECT
