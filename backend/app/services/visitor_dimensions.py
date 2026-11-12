"""
The visitor dimensions beyond country, device and browser family (#204):
operating system and its major version, browser major version, language,
hostname and screen size.

Two halves. The first reduces what a request says about its sender to values
coarse enough to report on and no finer; the second turns those columns into
dashboard reports and filters.

The reduction is the part that matters. The visitor hash rotates every day so
that nobody can be followed from one day to the next, and a row that also
carried a full user agent, a complete Accept-Language list and an exact OS
build would be a fingerprint that survives the rotation. So:

  - versions are the major number only, and only digits
  - operating systems are a fixed short list, with everything rare as "Other"
  - language is the first preference only, as language and region ("sv-SE"),
    with script, variant and the rest of the list thrown away
  - the raw user agent and the raw header are never stored

Everything here returns None rather than raising. A pageview is worth more
than any of its dimensions, and None is shown as "Unknown", which is also what
every row recorded before these columns existed says.
"""
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import Integer, and_, func, literal_column, select, tuple_
from sqlalchemy.orm import Session
from user_agents import parse

from app.models.pageview import Pageview

#: What a missing value is called, in reports and as a filter value. None of
#: the normalised values can collide with it: operating systems come from the
#: list below, languages and hostnames start with a lowercase letter or digit,
#: and versions and widths are digits.
UNKNOWN = "Unknown"

OTHER_OS = "Other"

_MAJOR = re.compile(r"^\d{1,4}$")

# ua-parser's family names, reduced to what a report needs. A distribution
# name says little about a website's audience and a lot about one visitor.
_LINUX_FAMILIES = frozenset({
    "linux", "ubuntu", "debian", "fedora", "arch linux", "linux mint",
    "red hat", "centos", "suse", "opensuse", "gentoo", "slackware", "mageia",
    "mandriva", "kubuntu", "xubuntu", "lubuntu", "manjaro", "puppy",
})

# Families whose version says something. Linux has none worth the name, and
# Chrome OS reports a build number, which is far finer than a major version.
_VERSIONED = frozenset({"Windows", "macOS", "iOS", "Android"})


def _major(version) -> Optional[str]:
    """The first component of a parsed version, if it is a plain number."""
    if not version:
        return None
    first = str(version[0]) if isinstance(version, (tuple, list)) else str(version)
    first = first.split(".")[0]
    return first if _MAJOR.match(first) else None


def _os_family(family: str) -> Optional[str]:
    name = (family or "").strip()
    lowered = name.lower()
    if not name or lowered == "other":
        return None
    if lowered == "windows":
        return "Windows"
    if lowered in ("mac os x", "macos", "mac os"):
        return "macOS"
    if lowered == "ios":
        return "iOS"
    if lowered == "android":
        return "Android"
    if lowered == "chrome os":
        return "Chrome OS"
    if lowered in _LINUX_FAMILIES:
        return "Linux"
    return OTHER_OS


def from_user_agent(user_agent: str) -> Dict[str, Optional[str]]:
    """Operating system, its major version and the browser's major version.

    The user agent is read here and dropped; only these three short values
    leave the function.
    """
    result = {"os": None, "os_version": None, "browser_version": None}
    if not user_agent:
        return result
    try:
        ua = parse(user_agent)
        os_name = _os_family(ua.os.family)
        result["os"] = os_name
        if os_name in _VERSIONED:
            result["os_version"] = _major(ua.os.version)
        if ua.browser.family and ua.browser.family != "Other":
            result["browser_version"] = _major(ua.browser.version)
    except Exception:  # noqa: BLE001
        return {"os": None, "os_version": None, "browser_version": None}
    return result


_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}$")
_REGION = re.compile(r"^[A-Za-z]{2}$")


def normalise_language(value) -> Optional[str]:
    """One language tag reduced to language and region: "sv-SE", or "sv".

    Accepts what navigator.language gives ("sv-SE", "zh-Hans-CN", "en") and
    the underscore form some clients send. Script, variant and extension
    subtags are dropped, and a tag that is not a language at all gives None.
    Given a whole preference list it keeps the first entry and nothing else,
    so a client that sends one cannot get it stored.
    """
    if not isinstance(value, str):
        return None
    first = value.split(",")[0].split(";")[0]
    parts = first.strip().replace("_", "-").split("-")
    if not parts or not _LANGUAGE.match(parts[0]):
        return None
    language = parts[0].lower()
    for part in parts[1:]:
        if _REGION.match(part):
            return f"{language}-{part.upper()}"
    return language


def language_from_accept_language(header: Optional[str]) -> Optional[str]:
    """The first preference of an Accept-Language header, normalised.

    Only the first. The full list with its weights is one of the better
    fingerprinting inputs a browser sends, and it is never stored.
    """
    return normalise_language(header) if header else None


_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
    r"(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)


def normalise_hostname(value) -> Optional[str]:
    """A hostname in lowercase without port or trailing dot, or None."""
    if not isinstance(value, str):
        return None
    host = value.strip().lower().rstrip(".")
    return host if _HOSTNAME.match(host) else None


def hostname_from_origin(origin: Optional[str]) -> Optional[str]:
    """The hostname of an Origin header, for a tracker that did not send one."""
    if not origin:
        return None
    try:
        return normalise_hostname(urlparse(origin).hostname)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Reports and filters
# ---------------------------------------------------------------------------

#: The reports in the order the dashboard shows them: filter name, heading.
#: The filter name is also the query parameter.
DIMENSIONS: List[Tuple[str, str]] = [
    ("os", "Operating systems"),
    ("os_version", "OS versions"),
    ("browser_version", "Browser versions"),
    ("language", "Languages"),
    ("hostname", "Hostnames"),
    ("screen", "Screen sizes"),
]

DIMENSION_NAMES = tuple(name for name, _ in DIMENSIONS)

_SIMPLE = {
    "os": Pageview.os,
    "language": Pageview.language,
    "hostname": Pageview.hostname,
}

# A version means nothing without what it is a version of, so these two are
# reported and filtered as a pair: "Chrome 126", "Windows 10".
_VERSIONED_PAIRS = {
    "os_version": (Pageview.os, Pageview.os_version),
    "browser_version": (Pageview.browser, Pageview.browser_version),
}

_REPORT_LIMIT = 10

# Screen width is reported in ranges, never as the exact number of pixels: an
# exact width narrows a visitor down far more than a report needs, and ranges
# are what the public data page says is shown. The boundaries are the
# breakpoints people design against. A range is named by its lower bound,
# which is also its filter value.
SCREEN_BOUNDS = (576, 768, 1024, 1280, 1440, 1920, 2560)

# width_bucket() gives the index of the range: 0 below the first boundary,
# len(SCREEN_BOUNDS) from the last one up, NULL for NULL. Written as literal
# SQL so that the expression is textually the same in GROUP BY and GROUPING(),
# which Postgres requires and bound parameters would not give.
_SCREEN_BUCKET = literal_column(
    "width_bucket(pageviews.screen_width, ARRAY[%s])"
    % ",".join(str(bound) for bound in SCREEN_BOUNDS),
    type_=Integer,
)


def _screen_range(index: int) -> Tuple[int, Optional[int]]:
    """Lower bound and exclusive upper bound of a range, None for open-ended."""
    low = SCREEN_BOUNDS[index - 1] if index > 0 else 0
    high = SCREEN_BOUNDS[index] if index < len(SCREEN_BOUNDS) else None
    return low, high


def _screen_row(index: Optional[int], count: int) -> Dict:
    if index is None:
        return _row(UNKNOWN, UNKNOWN, count)
    low, high = _screen_range(index)
    if high is None:
        label = f"{low} px and wider"
    elif low == 0:
        label = f"Under {high} px"
    else:
        label = f"{low} to {high - 1} px"
    return _row(str(low), label, count)


def _pair_condition(family_column, version_column, value: str):
    if value == UNKNOWN:
        return family_column.is_(None)
    family, _, version = value.rpartition(" ")
    if not family:
        return family_column == value
    if version == UNKNOWN:
        return and_(family_column == family, version_column.is_(None))
    return and_(family_column == family, version_column == version)


def dimension_conditions(filters: Optional[Dict[str, str]]) -> List:
    """SQL conditions for the dimension filters that are set.

    "Unknown" selects the rows without a value, so the row every report shows
    for older pageviews can be clicked like any other.
    """
    conditions = []
    for name, value in (filters or {}).items():
        if not value:
            continue
        if name in _SIMPLE:
            column = _SIMPLE[name]
            conditions.append(column.is_(None) if value == UNKNOWN else column == value)
        elif name in _VERSIONED_PAIRS:
            conditions.append(_pair_condition(*_VERSIONED_PAIRS[name], value))
        elif name == "screen":
            if value == UNKNOWN:
                conditions.append(Pageview.screen_width.is_(None))
            elif value.isdigit() and int(value) in (0, *SCREEN_BOUNDS):
                low, high = _screen_range(
                    SCREEN_BOUNDS.index(int(value)) + 1 if int(value) else 0
                )
                conditions.append(Pageview.screen_width >= low)
                if high is not None:
                    conditions.append(Pageview.screen_width < high)
            else:
                # Not the start of a range. Matching nothing is the honest
                # answer to a filter that cannot match; ignoring it would
                # show everything under a chip that says it is filtered.
                conditions.append(Pageview.id.is_(None))
    return conditions


def _row(value: str, label: str, views: int) -> Dict:
    return {"value": value, "label": label, "views": views}


# Every column any report groups on, and which of them each report uses. One
# statement with GROUPING SETS answers all six from a single pass over the
# range; six separate queries would be six passes, on a page that refreshes
# its numbers every ten seconds.
_REPORT_COLUMNS = (
    Pageview.os,
    Pageview.os_version,
    Pageview.browser,
    Pageview.browser_version,
    Pageview.language,
    Pageview.hostname,
    _SCREEN_BUCKET,
)
_REPORT_SETS = {
    "os": (0,),
    "os_version": (0, 1),
    "browser_version": (2, 3),
    "language": (4,),
    "hostname": (5,),
    "screen": (6,),
}


def _grouping_id(used: Tuple[int, ...]) -> int:
    """What GROUPING(all columns) returns for the set that groups on `used`.

    One bit per column, the first column highest, set when the column is NOT
    part of the grouping set.
    """
    width = len(_REPORT_COLUMNS)
    return sum(1 << (width - 1 - i) for i in range(width) if i not in used)


def _pair_row(family, version, count) -> Dict:
    if not family:
        return _row(UNKNOWN, UNKNOWN, count)
    if not version:
        return _row(f"{family} {UNKNOWN}", f"{family} (unknown version)", count)
    return _row(f"{family} {version}", f"{family} {version}", count)


def _plain_row(value, count) -> Dict:
    return _row(value or UNKNOWN, value or UNKNOWN, count)


def dimension_reports(db: Session, conditions: List) -> Dict[str, List[Dict]]:
    """The top values of every dimension among the pageviews `conditions` allow.

    Rows without a value are counted, not hidden, and come back as "Unknown":
    every pageview recorded before the columns existed is one of them, and a
    report that left them out would add up to less than the number above it.
    """
    views = func.count(Pageview.id)
    grouping_id = func.grouping(*_REPORT_COLUMNS)
    grouped = (
        select(
            *[column.label(f"c{i}") for i, column in enumerate(_REPORT_COLUMNS)],
            grouping_id.label("grouping_id"),
            views.label("views"),
            func.row_number()
            .over(partition_by=grouping_id, order_by=views.desc())
            .label("position"),
        )
        .where(and_(*conditions))
        .group_by(
            func.grouping_sets(
                *[
                    tuple_(*[_REPORT_COLUMNS[i] for i in used])
                    for used in _REPORT_SETS.values()
                ]
            )
        )
        .subquery()
    )
    rows = db.execute(
        select(grouped)
        .where(grouped.c.position <= _REPORT_LIMIT)
        .order_by(grouped.c.grouping_id, grouped.c.position)
    ).all()

    name_of = {_grouping_id(used): name for name, used in _REPORT_SETS.items()}
    reports: Dict[str, List[Dict]] = {name: [] for name in DIMENSION_NAMES}
    for row in rows:
        name = name_of[row.grouping_id]
        if name == "os":
            item = _plain_row(row.c0, row.views)
        elif name == "os_version":
            item = _pair_row(row.c0, row.c1, row.views)
        elif name == "browser_version":
            item = _pair_row(row.c2, row.c3, row.views)
        elif name == "language":
            item = _plain_row(row.c4, row.views)
        elif name == "hostname":
            item = _plain_row(row.c5, row.views)
        else:
            item = _screen_row(row.c6, row.views)
        reports[name].append(item)
    return reports
