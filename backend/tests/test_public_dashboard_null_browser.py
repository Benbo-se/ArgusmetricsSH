"""The public dashboard must render a pageview that has no browser.

The browser list picked its icon with `'Chrome' in browser.browser`, and `in`
on None raises, so one such row in the range turned the whole page into a 500.
"""
from sqlalchemy import text


def test_a_pageview_without_a_browser_does_not_break_the_public_page(
    client, db, shared_website
):
    db.execute(
        text(
            'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp", '
            "  browser, device_type) "
            "VALUES (:w, '/', 'nobrowser', now() - interval '1 minute', NULL, 'desktop')"
        ),
        {"w": shared_website["id"]},
    )
    db.commit()

    page = client.get(f"/public/{shared_website['share_token']}?range=7d")
    assert page.status_code == 200
    assert '<span class="text-sm text-gray-700">Unknown</span>' in page.text
