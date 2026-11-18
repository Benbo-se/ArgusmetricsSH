"""
How every Argusmetrics mail looks.

One frame, used by all of them: the night band with the name and a day of
traffic, the vellum sheet under it, peacock for what can be pressed and iris
gold for the small labels. The same four colours as the dashboard
(static/css/theme.css) and the public site.

What a mail client allows decides the rest. Tables and inline styles, because
Outlook and Gmail drop most of a stylesheet. No images and no web fonts,
because both are fetched from a server when the mail is opened, and a mail
from an analytics tool that does not track people should not report its own
opening. The typefaces are named first and fall back to what the reader has.

Everything a caller passes in as `*_html` is already escaped by the caller;
everything else is escaped here.
"""
from html import escape
from typing import Iterable, List, Optional, Sequence, Tuple

from app.config import settings

NIGHT = "#0a0d16"
NIGHT_TEXT = "#e9ecf7"
NIGHT_FAINT = "#3a4259"
PAGE = "#f3efe6"
SHEET = "#fcfaf5"
SUNKEN = "#ebe6d9"
LINE = "#e2dccd"
INK = "#151826"
INK_DIM = "#4b5063"
INK_FAINT = "#7a7e8e"
PEACOCK = "#1fc7b3"
PEACOCK_DEEP = "#0a6f69"
IRIS = "#e8b955"
IRIS_DEEP = "#9c6c12"

SANS = "'Familjen Grotesk','Helvetica Neue',Helvetica,Arial,sans-serif"
SERIF = "Newsreader,Georgia,'Times New Roman',serif"
MONO = "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

# The day the mark is drawn with (site-src/_mark.html): sixteen hours gone,
# the seventeenth under way, the rest still ahead.
_ORDINARY_DAY = [4.0, 3.8, 3.6, 3.5, 3.6, 4.0, 4.6, 5.3, 5.9, 6.2, 7.6, 7.1, 6.8, 6.7, 6.9, 6.5]


def _day_strip() -> str:
    """The mark's day, unrolled: one bar an hour, gold for the hour we are in."""
    tallest = max(_ORDINARY_DAY)
    cells = []
    for hour in range(24):
        if hour < len(_ORDINARY_DAY):
            height, colour = round(5 + 17 * _ORDINARY_DAY[hour] / tallest), PEACOCK
            if hour == len(_ORDINARY_DAY) - 1:
                colour = IRIS
        else:
            height, colour = 3, NIGHT_FAINT
        cells.append(
            f'<td valign="bottom" style="padding:0 0 0 2px;vertical-align:bottom;">'
            f'<div style="width:4px;height:{height}px;background:{colour};font-size:0;line-height:0;">&nbsp;</div></td>'
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="right">'
        f'<tr>{"".join(cells)}</tr></table>'
    )


def text(html: str, *, small: bool = False) -> str:
    """A paragraph of body copy."""
    if small:
        return (f'<p style="margin:0 0 12px;font-family:{SANS};font-size:13px;line-height:1.55;'
                f'color:{INK_FAINT};">{html}</p>')
    return (f'<p style="margin:0 0 18px;font-family:{SANS};font-size:16px;line-height:1.6;'
            f'color:{INK_DIM};">{html}</p>')


def strong(value) -> str:
    return f'<strong style="color:{INK};font-weight:700;">{escape(str(value))}</strong>'


def aside(value) -> str:
    """The italic the headings lean on for the one phrase that matters."""
    return (f'<span style="font-family:{SERIF};font-style:italic;font-weight:400;'
            f'color:{PEACOCK_DEEP};">{escape(str(value))}</span>')


def label(value) -> str:
    return (f'<span style="font-family:{MONO};font-size:11px;letter-spacing:.14em;'
            f'text-transform:uppercase;color:{IRIS_DEEP};">{escape(str(value))}</span>')


def button(caption: str, url: str) -> str:
    """The one thing to press, and the address spelled out under it for the
    clients and scanners that make a button awkward."""
    href = escape(str(url))
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:26px 0 14px;">'
        f'<tr><td bgcolor="{PEACOCK_DEEP}" style="background:{PEACOCK_DEEP};border-radius:6px;">'
        f'<a href="{href}" style="display:inline-block;padding:14px 26px;font-family:{SANS};font-size:15px;'
        f'font-weight:700;color:#ffffff;text-decoration:none;">{escape(caption)}&nbsp;&nbsp;&rarr;</a>'
        '</td></tr></table>'
        f'<p style="margin:0 0 22px;font-family:{MONO};font-size:11px;line-height:1.6;color:{INK_FAINT};'
        f'word-break:break-all;">or open&nbsp; <a href="{href}" style="color:{PEACOCK_DEEP};">{href}</a></p>'
    )


def ledger(rows: Sequence[Tuple[str, str]]) -> str:
    """Name and value, one to a line, ruled like an account book."""
    out = []
    for name, value_html in rows:
        out.append(
            f'<tr><td style="padding:11px 16px 11px 0;border-top:1px solid {LINE};white-space:nowrap;'
            f'vertical-align:top;">{label(name)}</td>'
            f'<td style="padding:9px 0;border-top:1px solid {LINE};font-family:{SANS};font-size:15px;'
            f'line-height:1.5;color:{INK};">{value_html}</td></tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:6px 0 8px;border-bottom:1px solid {LINE};">{"".join(out)}</table>'
    )


def code(value) -> str:
    """A code to be typed by hand: wide apart and impossible to miss."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 22px;">'
        f'<tr><td style="background:{SUNKEN};border-radius:6px;padding:14px 22px;font-family:{MONO};'
        f'font-size:30px;font-weight:700;letter-spacing:8px;color:{INK};">{escape(str(value))}</td></tr></table>'
    )


def figures(items: Sequence[Tuple[str, str, Optional[str]]]) -> str:
    """The numbers the mail is about, side by side: (name, value, note)."""
    width = 100 // max(len(items), 1)
    cells = []
    for name, value, note in items:
        note_html = (f'<div style="font-family:{SANS};font-size:13px;color:{INK_FAINT};padding-top:2px;">'
                     f'{escape(note)}</div>') if note else ""
        cells.append(
            f'<td width="{width}%" style="padding:0 12px 0 0;vertical-align:top;">{label(name)}'
            f'<div style="font-family:{SANS};font-size:38px;line-height:1.15;font-weight:700;'
            f'letter-spacing:-.02em;color:{INK};padding-top:4px;">{escape(str(value))}</div>{note_html}</td>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:4px 0 26px;"><tr>{"".join(cells)}</tr></table>'
    )


def chart(values: Sequence[int], captions: Sequence[str], *, height: int = 96) -> str:
    """Bars for a run of days, drawn with table cells so every client shows
    them. The last bar is the newest and carries the gold."""
    if not values:
        return ""
    top = max(max(values), 1)
    width = 100 / len(values)
    bars, names = [], []
    for position, value in enumerate(values):
        tall = max(round(height * value / top), 2)
        colour = IRIS_DEEP if position == len(values) - 1 else PEACOCK_DEEP
        if value == 0:
            colour = LINE
        bars.append(
            f'<td width="{width:.2f}%" valign="bottom" style="vertical-align:bottom;padding:0 2px;">'
            f'<div style="height:{tall}px;background:{colour};border-radius:2px 2px 0 0;font-size:0;'
            f'line-height:0;">&nbsp;</div></td>'
        )
        caption = captions[position] if position < len(captions) else ""
        names.append(
            f'<td align="center" style="padding:6px 0 0;font-family:{MONO};font-size:10px;'
            f'color:{INK_FAINT};">{escape(caption)}</td>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:0 0 28px;table-layout:fixed;"><tr style="height:{height}px;">{"".join(bars)}</tr>'
        f'<tr>{"".join(names)}</tr></table>'
    )


def ranking(title: str, rows: Iterable[Tuple[str, int]], unit: str = "") -> str:
    """A top list. Each line carries its own share of the largest as a rule
    under the name, so the list reads as a chart without being one."""
    rows = list(rows)
    if not rows:
        return ""
    top = max(max(count for _, count in rows), 1)
    out = [f'<tr><td colspan="2" style="padding:0 0 8px;">{label(title)}</td></tr>']
    for name, count in rows:
        share = max(round(100 * count / top), 2)
        out.append(
            f'<tr><td style="padding:8px 12px 5px 0;font-family:{SANS};font-size:15px;color:{INK};'
            f'word-break:break-all;">{escape(str(name))}</td>'
            f'<td align="right" style="padding:8px 0 5px;font-family:{MONO};font-size:13px;color:{INK_DIM};'
            f'white-space:nowrap;">{count:,}{escape(unit)}</td></tr>'
            f'<tr><td colspan="2" style="padding:0 0 4px;"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0" border="0"><tr><td style="background:{SUNKEN};font-size:0;'
            f'line-height:0;"><div style="width:{share}%;height:3px;background:{PEACOCK_DEEP};font-size:0;'
            f'line-height:0;">&nbsp;</div></td></tr></table></td></tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:0 0 28px;">{"".join(out)}</table>'
    )


def comparison(rows: Sequence[Tuple[str, int, bool]]) -> str:
    """Two or three amounts on the same scale: (name, amount, is the one that matters)."""
    top = max(max(amount for _, amount, _ in rows), 1)
    out = []
    for name, amount, marked in rows:
        share = max(round(100 * amount / top), 1)
        colour = IRIS_DEEP if marked else PEACOCK_DEEP
        out.append(
            f'<tr><td style="padding:10px 0 4px;">{label(name)}</td>'
            f'<td align="right" style="padding:10px 0 4px;font-family:{MONO};font-size:13px;color:{INK};">'
            f'{amount:,}</td></tr>'
            f'<tr><td colspan="2"><div style="width:{share}%;height:10px;background:{colour};'
            f'border-radius:2px;font-size:0;line-height:0;">&nbsp;</div></td></tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:0 0 26px;">{"".join(out)}</table>'
    )


def render(*, eyebrow: str, heading_html: str, body: List[str], preheader: str = "",
           reason: str = "") -> str:
    """The whole mail. `body` is a list of the pieces above, in reading order."""
    name = escape(settings.APP_NAME)
    home = escape(settings.BASE_URL)
    host = escape(settings.BASE_URL.split("://", 1)[-1].rstrip("/"))
    reason_html = f"{escape(reason)}<br>" if reason else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{name}</title>
</head>
<body style="margin:0;padding:0;background:{PAGE};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{PAGE};">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAGE}" style="background:{PAGE};">
<tr><td align="center" style="padding:28px 12px 36px;">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:560px;">
<tr><td bgcolor="{NIGHT}" style="background:{NIGHT};border-radius:10px 10px 0 0;padding:20px 32px 18px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="font-family:{SANS};font-size:18px;font-weight:700;letter-spacing:-.01em;color:{NIGHT_TEXT};vertical-align:bottom;"><a href="{home}" style="color:{NIGHT_TEXT};text-decoration:none;">{name}</a></td>
<td align="right" style="vertical-align:bottom;">{_day_strip()}</td>
</tr></table>
</td></tr>
<tr><td bgcolor="{SHEET}" style="background:{SHEET};border:1px solid {LINE};border-top:0;border-radius:0 0 10px 10px;padding:34px 32px 22px;">
<div style="margin:0 0 12px;">{label(eyebrow)}</div>
<h1 style="margin:0 0 20px;font-family:{SANS};font-size:28px;line-height:1.18;font-weight:700;letter-spacing:-.02em;color:{INK};">{heading_html}</h1>
{"".join(body)}
</td></tr>
<tr><td style="padding:18px 32px 0;font-family:{SANS};font-size:12px;line-height:1.6;color:{INK_FAINT};">
{reason_html}{name}, web analytics without cookies. <a href="{home}" style="color:{INK_FAINT};">{host}</a>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
