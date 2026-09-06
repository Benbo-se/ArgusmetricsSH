"""Images ship to visitors, so their size is a feature of the product.

The repository was carrying nine megabytes of images nothing referenced: six
design mockups committed by accident, and four superseded copies of the same
icon. That costs a clone and nothing else, so it is untidy rather than
harmful.

The one that reached visitors was favicon.ico: 535 kilobytes at 1024 by 1024,
fetched by every browser that opens the site, for an image drawn at sixteen
pixels. A tab icon that weighs more than the page it sits on.

Both are the kind of thing nobody looks at, so this looks at them.
"""
import pathlib
import struct

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: No single image should be heavier than this. Nothing here needs to be, and
#: an image that does is either a mistake or a decision worth making on
#: purpose, in which case add it below with a reason.
MAX_IMAGE_BYTES = 250 * 1024

#: An icon is drawn at 16 to 48 pixels. Anything larger is bytes nobody sees.
MAX_ICON_BYTES = 32 * 1024
MAX_ICON_DIMENSION = 64

DELIBERATELY_LARGE: dict = {
    # path -> why. Empty on purpose: nothing currently needs an exception.
}

pytestmark = pytest.mark.skipif(
    not (ROOT / "site").is_dir(),
    reason="the whole repository is not in this checkout (the development "
           "container mounts only backend/). Expected to run in CI.",
)


def _images():
    for directory in (ROOT / "site", ROOT / "backend" / "app" / "static"):
        for path in directory.rglob("*"):
            if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".ico", ".gif"):
                yield path


def _ico_dimensions(path: pathlib.Path):
    """The sizes inside an .ico, without a decoder.

    The format is a six-byte header then a sixteen-byte entry per image, whose
    first two bytes are width and height. Zero means 256, which is the format
    admitting it never expected to be asked for more.
    """
    data = path.read_bytes()
    _reserved, _kind, count = struct.unpack("<HHH", data[:6])
    sizes = []
    for i in range(count):
        offset = 6 + i * 16
        width, height = data[offset], data[offset + 1]
        sizes.append((width or 256, height or 256))
    return sizes


class TestNothingIsUnreasonablyHeavy:
    def test_there_are_images_to_weigh(self):
        """A path that stops matching turns this into a test that passes on
        an empty list, which is how a budget quietly stops applying."""
        assert len(list(_images())) >= 10

    def test_no_image_is_over_the_budget(self):
        heavy = [
            f"{p.relative_to(ROOT)}: {p.stat().st_size // 1024} KB"
            for p in _images()
            if p.stat().st_size > MAX_IMAGE_BYTES
            and str(p.relative_to(ROOT)) not in DELIBERATELY_LARGE
        ]
        assert not heavy, (
            f"these images are over {MAX_IMAGE_BYTES // 1024} KB:\n  "
            + "\n  ".join(heavy)
            + "\n\nResize it, or add it to DELIBERATELY_LARGE with a reason."
        )


class TestTheFaviconIsAFavicon:
    """It is fetched by every browser that opens the site, once per visitor,
    for something drawn at sixteen pixels."""

    def _icons(self):
        return [p for p in _images() if p.suffix.lower() == ".ico"]

    def test_there_is_one(self):
        assert self._icons(), "no .ico found; this test would pass silently"

    def test_it_is_small(self):
        heavy = [
            f"{p.relative_to(ROOT)}: {p.stat().st_size // 1024} KB"
            for p in self._icons()
            if p.stat().st_size > MAX_ICON_BYTES
        ]
        assert not heavy, (
            f"a favicon over {MAX_ICON_BYTES // 1024} KB is downloaded by "
            "every visitor for an image drawn at 16 pixels:\n  "
            + "\n  ".join(heavy)
        )

    def test_it_does_not_contain_a_wall_poster(self):
        """The actual defect: 1024 by 1024, in a file browsers render at 16."""
        oversized = []
        for path in self._icons():
            for width, height in _ico_dimensions(path):
                if max(width, height) > MAX_ICON_DIMENSION:
                    oversized.append(
                        f"{path.relative_to(ROOT)} contains a {width}x{height} image"
                    )
        assert not oversized, "\n  ".join([""] + oversized)

    def test_it_offers_the_sizes_browsers_ask_for(self):
        """One 48-pixel image in an .ico is scaled down badly at 16."""
        for path in self._icons():
            sizes = {w for w, _h in _ico_dimensions(path)}
            assert 16 in sizes and 32 in sizes, (
                f"{path.relative_to(ROOT)} has sizes {sorted(sizes)}; browsers "
                "ask for 16 and 32"
            )


class TestNothingUnreferencedCreepsBack:
    """The six design mockups sat in the repository root for months.

    Not a general unused-file check, which would be noisy and wrong. Just the
    shape that happened: images at the top level, where nothing serves from.
    """

    def test_the_repository_root_holds_no_images(self):
        stray = [
            p.name for p in ROOT.iterdir()
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif")
        ]
        assert not stray, (
            f"images in the repository root: {stray}. Nothing is served from "
            "here, so these reach nobody and are carried by every clone."
        )
