"""The entrance animation must not outlive itself on the dashboard sections.

A fill mode that keeps the last keyframe (`both` or `forwards`) holds the
`transform` of dash-rise on every section after the animation ends. Any
transform, even `none` as a keyframe value, is applied by the animation layer
and gives the element its own stacking context, so a dropdown with z-50 in one
section is painted under the next section. `backwards` only applies the first
keyframe during the delay, and the element ends in its ordinary style.
"""
import re
from pathlib import Path

THEME = Path(__file__).resolve().parents[1] / "app" / "static" / "css" / "theme.css"


def _declarations_using(keyframes):
    css = re.sub(r"/\*.*?\*/", "", THEME.read_text(), flags=re.S)
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for declaration in body.split(";"):
            name, _, value = declaration.partition(":")
            if name.strip() in ("animation", "animation-name") and keyframes in value:
                yield selector.strip(), declaration.strip()


def test_the_section_animation_does_not_hold_its_last_frame():
    found = list(_declarations_using("dash-rise"))
    assert found, "dash-rise is no longer used; this guard is looking at nothing"
    for selector, declaration in found:
        words = declaration.split()
        assert "both" not in words and "forwards" not in words, (
            f"{selector} keeps the final keyframe, which leaves a stacking "
            f"context on every section: {declaration}"
        )

