"""
What a report is filtered on: one object, compiled to SQL in one place (#197).

A filter is a dimension, an operator and a value: "country is SE", "page
contains /blog", "referrer is not https://example.com/". A FilterSet is the
filters of one request, all of which must hold.

Before this the query layer took six named parameters, one per dimension, and
every one was threaded through the router, the service and the template and
compared with `==`. A new dimension meant touching five places, an operator
other than equality had nowhere to go, and goals, events, funnels and revenue
never saw a filter at all.

Four things live here and nowhere else:

  - which dimensions exist and which operators each takes (DIMENSIONS)
  - how a filter is written in a query string, and read back (from_query,
    query_items), so the page, its ten-second refresh, the CSV export and the
    JSON API cannot disagree about it
  - how a filter becomes SQL (conditions, visitor_conditions)
  - which pageviews are counted at all, before any filter is applied (counted)

A value only ever reaches the database as a bound parameter. "contains"
escapes the LIKE wildcards in it, so a search for "50%" finds a per cent sign
and not everything that begins with 50.
"""
import json
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlencode

from sqlalchemy import and_, false, func, not_, or_, select

from app.models.pageview import Pageview
from app.models.website import Website
from app.services import visitor_dimensions
from app.services.visitor_dimensions import UNKNOWN

# A page is its path. The tracker stores the query string too, so a campaign
# click on /pricing is /pricing?fbclid=abc, and grouping on the raw column gives
# every click its own row. Readers compare this instead; the stored path is left
# as it was, which is why history needs no migration.
#
# Every dashboard query is bounded by website_id and a timestamp range, which
# idx_pageviews_website_timestamp serves. The (website_id, path, timestamp)
# index cannot serve an expression, and nothing here relied on it for more
# than a narrower scan inside that range.
PAGE_PATH = func.split_part(Pageview.path, "?", 1)


def counted(website_id):
    """The condition every number about visitors starts from (#103).

    A pageview labelled at collection as coming from a hosting provider is
    stored and not counted: not in a total, a graph, a top list, the live
    view, an export or an email. Unless the website has turned that off, in
    which case its labelled rows count like any other.

    The setting is read inside the query, by a subquery on the website's own
    row, so nothing has to carry it here: a caller that knows the website id
    cannot get it wrong, and one written next year gets it by using this.
    Postgres evaluates the subquery once per statement, and only if it meets
    a labelled row at all.

    It fails closed. Where the row cannot be read (a context without a policy
    on websites, a website that is gone) the subquery is NULL, NULL is not
    false, and labelled rows stay out. That is the default, so a mistake here
    looks like the setting not taking effect, not like crawlers coming back.

    `website_id` is a number, or a column to correlate with in a query over
    several websites.

    The raw SQL in site_activity.py spells the same rule by hand. A test
    holds the two together.
    """
    excluded = (
        select(Website.exclude_datacenter)
        .where(Website.id == website_id)
        .scalar_subquery()
    )
    return or_(Pageview.traffic_class.is_(None), excluded.is_(False))


def left_out(website_id):
    """The other side of counted(): labelled, on a website that excludes.

    Only for saying how much was left out. Written out, not negated: NOT
    (NULL OR false) is NULL, which would match nothing where the setting
    could not be read, and the line on the dashboard would say nothing was
    kept out while everything was.
    """
    excluded = (
        select(Website.exclude_datacenter)
        .where(Website.id == website_id)
        .scalar_subquery()
    )
    return and_(Pageview.traffic_class.isnot(None), excluded.isnot(False))


#: The operators, with the suffix each adds to the dimension's name in a query
#: string and the words a person reads. "is" has no suffix, so the links that
#: existed before operators did (?country=SE) mean what they always meant.
OPERATORS: Dict[str, Tuple[str, str]] = {
    "is": ("", "is"),
    "is_not": ("__not", "is not"),
    "contains": ("__contains", "contains"),
    "not_contains": ("__not_contains", "does not contain"),
}

_EXACT = ("is", "is_not")
_ALL = tuple(OPERATORS)

#: As long as the longest stored value (a path or a referrer is at most 2048
#: characters), and short enough that a query string cannot be used to hand
#: the database a megabyte to search for.
MAX_VALUE_LENGTH = 2048

#: How many custom properties one request may filter on.
MAX_PROPERTIES = 10


def _text(column, unknown: bool = False) -> Callable:
    """Conditions on a text column or expression.

    `unknown` is for the columns whose missing value a report shows as
    "Unknown": that row can then be clicked like any other. Both spellings are
    matched, because the browser column holds NULL for some rows and the word
    itself for others.
    """
    def match(value: str, contains: bool):
        if contains:
            return column.icontains(value, autoescape=True)
        if unknown and value == UNKNOWN:
            return or_(column.is_(None), column == UNKNOWN)
        return column == value
    return match


def _pair(name: str) -> Callable:
    def match(value: str, contains: bool):
        if contains:
            return visitor_dimensions.pair_text(name).icontains(value, autoescape=True)
        return visitor_dimensions.pair_condition(name, value)
    return match


def _screen(value: str, contains: bool):
    return visitor_dimensions.screen_condition(value)


@dataclass(frozen=True)
class Dimension:
    """Something a pageview can be filtered on."""
    name: str
    #: In the singular, as it reads in front of an operator: "Country is ...".
    label: str
    match: Callable
    operators: Tuple[str, ...] = _ALL


#: Every dimension, in the order the filter dialog lists them. The name is
#: also the query parameter. Country, device and screen size take whole values
#: only: a country is a two-letter code and a screen size is a range, and
#: "contains" on either would be answering a question nobody meant to ask.
DIMENSIONS: Dict[str, Dimension] = {
    d.name: d for d in (
        Dimension("page", "Page", _text(PAGE_PATH)),
        Dimension("referrer", "Referrer", _text(Pageview.referrer)),
        Dimension("utm_source", "UTM source", _text(Pageview.utm_source)),
        Dimension("utm_medium", "UTM medium", _text(Pageview.utm_medium)),
        Dimension("utm_campaign", "UTM campaign", _text(Pageview.utm_campaign)),
        Dimension("utm_content", "UTM content", _text(Pageview.utm_content)),
        Dimension("utm_term", "UTM term", _text(Pageview.utm_term)),
        Dimension("country", "Country", _text(Pageview.country), _EXACT),
        Dimension("language", "Language", _text(Pageview.language, unknown=True)),
        Dimension("hostname", "Hostname", _text(Pageview.hostname, unknown=True)),
        Dimension("device", "Device", _text(Pageview.device_type, unknown=True), _EXACT),
        Dimension("browser", "Browser", _text(Pageview.browser, unknown=True)),
        Dimension("browser_version", "Browser version", _pair("browser_version")),
        Dimension("os", "Operating system", _text(Pageview.os, unknown=True)),
        Dimension("os_version", "OS version", _pair("os_version")),
        Dimension("screen", "Screen size", _screen, _EXACT),
    )
}


@dataclass(frozen=True)
class Filter:
    dimension: str
    operator: str
    value: str

    @property
    def key(self) -> str:
        """The query parameter this filter is written as."""
        return self.dimension + OPERATORS[self.operator][0]

    @property
    def label(self) -> str:
        return DIMENSIONS[self.dimension].label

    @property
    def operator_label(self) -> str:
        return OPERATORS[self.operator][1]

    def condition(self):
        """This filter as a condition on pageviews."""
        contains = self.operator in ("contains", "not_contains")
        matched = DIMENSIONS[self.dimension].match(self.value, contains)
        if self.operator in ("is_not", "not_contains"):
            # A row without a value is not the value, so it belongs on the
            # "is not" side. A bare NOT would leave it out of both: NULL = 'SE'
            # is NULL, and so is its negation.
            return not_(func.coalesce(matched, false()))
        return matched


def _clean_properties(raw) -> Dict[str, object]:
    """The custom property filter, as a flat object of plain values or nothing.

    It arrives as JSON in the query string. Anything that is not an object of
    strings, numbers and booleans is dropped: the containment test below would
    accept a list or a nested object and answer a question the page has no
    way to show.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict) or len(raw) > MAX_PROPERTIES:
        return {}
    clean = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key or len(key) > MAX_VALUE_LENGTH:
            return {}
        if isinstance(value, str):
            if len(value) > MAX_VALUE_LENGTH:
                return {}
        elif value is None or not isinstance(value, (bool, int, float)):
            return {}
        clean[key] = value
    return clean


class FilterSet:
    """The filters of one request. Every one of them must hold."""

    def __init__(self, filters: Tuple[Filter, ...] = (), properties: Optional[Dict] = None):
        self.filters = tuple(filters)
        self.properties = dict(properties or {})

    @classmethod
    def from_query(cls, params: Mapping) -> "FilterSet":
        """Read the filters out of a query string, or any mapping shaped like one.

        Only the parameters a dimension and an operator spell out are read, so
        the range, the comparison and anything unknown pass by untouched. An
        empty value is no filter, and so is one too long to be a stored value.
        """
        found = []
        for dimension in DIMENSIONS.values():
            for operator in dimension.operators:
                value = params.get(dimension.name + OPERATORS[operator][0])
                if isinstance(value, str) and value and len(value) <= MAX_VALUE_LENGTH:
                    found.append(Filter(dimension.name, operator, value))
        return cls(tuple(found), _clean_properties(params.get("properties")))

    @classmethod
    def of(cls, **params) -> "FilterSet":
        """FilterSet.of(page="/pricing", country__not="SE"), for code and tests."""
        return cls.from_query(params)

    def __bool__(self) -> bool:
        return bool(self.filters or self.properties)

    def __repr__(self) -> str:
        # The names and not the values: this is what the log lines print, and
        # a property filter is as likely as not to hold a customer's id.
        names = [f.key for f in self.filters] + [f"properties.{key}" for key in self.properties]
        return f"FilterSet({', '.join(names)})"

    def conditions(self) -> List:
        """Conditions on pageviews, to be ANDed with the site and the range."""
        conditions = [f.condition() for f in self.filters]
        if self.properties:
            conditions.append(Pageview.properties.contains(self.properties))
        return conditions

    def visitor_conditions(self, visitor_column, website_id: int, start, end=None) -> List:
        """Narrow rows of another table to the visitors these filters let through.

        A goal conversion, a custom event, a funnel step or a purchase has no
        language, no hostname and no campaign of its own. What it has is the
        visitor's hash, the same one their pageviews carry. So a filter on such
        a report means: by visitors who have a matching pageview in the range.
        That is also how a filter picks visits (see _get_visit_stats), and it
        is one rule for every dimension instead of a second set of columns
        that could only ever cover some of them.

        Empty when nothing is filtered, so an unfiltered report runs the query
        it always ran.
        """
        if not self:
            return []
        matching = [
            Pageview.website_id == website_id,
            Pageview.timestamp >= start,
            counted(website_id),
        ]
        if end is not None:
            matching.append(Pageview.timestamp <= end)
        return [
            visitor_column.in_(
                select(Pageview.visitor_hash).where(and_(*matching, *self.conditions()))
            )
        ]

    def query_items(self) -> List[Tuple[str, str]]:
        """The filters as query parameters, the form from_query reads."""
        items = [(f.key, f.value) for f in self.filters]
        if self.properties:
            items.append(("properties", json.dumps(self.properties, sort_keys=True)))
        return items

    def query_string(self) -> str:
        # quote rather than quote_plus: a path keeps its slashes and stays
        # readable in the address, which is how the page has always written it.
        return urlencode(self.query_items(), safe="/", quote_via=quote)

    def dimensions(self) -> Dict[str, str]:
        """Which dimensions are filtered, for a template to mark them."""
        return {f.dimension: f.value for f in self.filters}


def visitor_conditions(
    filters: Optional[FilterSet], visitor_column, website_id: int, start, end=None
) -> List:
    """FilterSet.visitor_conditions for a report whose filters may be None."""
    if not filters:
        return []
    return filters.visitor_conditions(visitor_column, website_id, start, end)
