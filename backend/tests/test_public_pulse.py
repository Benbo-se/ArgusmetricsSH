"""The public dashboard's numbers as JSON, for a page that shows its own traffic.

It must answer with nothing the public page at the same token does not
already print, and must refuse exactly where that page refuses.
"""
from sqlalchemy import text

ALLOWED_TOP = {"name", "timezone", "online", "month", "today", "top_pages"}


def _view(db, website_id, path="/", minutes_ago=5):
    db.execute(
        text(
            'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp", browser, device_type, country) '
            "VALUES (:w, :p, :h, now() - make_interval(mins => :m), 'Chrome', 'desktop', 'SE')"
        ),
        {"w": website_id, "p": path, "h": f"v{minutes_ago}", "m": minutes_ago},
    )


def test_it_answers_what_the_public_page_shows_and_no_more(client, db, shared_website):
    _view(db, shared_website["id"], "/", 5)
    _view(db, shared_website["id"], "/pricing", 7)
    db.commit()

    answer = client.get(f"/public/{shared_website['share_token']}/pulse.json")
    assert answer.status_code == 200
    assert "max-age" in answer.headers["cache-control"]
    body = answer.json()
    assert set(body) == ALLOWED_TOP
    assert body["month"]["pageviews"] == 2
    assert body["month"]["visitors"] == 2
    assert {p["path"] for p in body["top_pages"]} == {"/", "/pricing"}
    for point in body["month"]["days"] + body["today"]["hours"]:
        assert set(point) == {"at", "visitors", "views"}
    for page in body["top_pages"]:
        assert set(page) == {"path", "views"}
    # Nothing that says who: no hash, country, referrer, id or token anywhere.
    raw = answer.text
    for word in ("visitor_hash", "country", "referrer", "tracking_code", shared_website["share_token"], '"id"'):
        assert word not in raw, word


def test_it_refuses_where_the_page_refuses(client, db, website, shared_website):
    assert client.get("/public/not-a-token/pulse.json").status_code == 404

    # Sharing switched off: the token stops answering.
    db.execute(text("UPDATE websites SET is_public = false WHERE id = :w"), {"w": website["id"]})
    db.commit()
    assert client.get(f"/public/{shared_website['share_token']}/pulse.json").status_code == 404

    # Behind a password, with no cookie from having typed it.
    db.execute(
        text(
            "UPDATE websites SET is_public = true, public_password_enabled = true, "
            "public_password_hash = 'x' WHERE id = :w"
        ),
        {"w": website["id"]},
    )
    db.commit()
    assert client.get(f"/public/{shared_website['share_token']}/pulse.json").status_code == 401


def test_it_only_counts_its_own_website(client, db, shared_website, second_website):
    _view(db, second_website["id"], "/secret", 3)
    _view(db, shared_website["id"], "/", 4)
    db.commit()

    body = client.get(f"/public/{shared_website['share_token']}/pulse.json").json()
    assert body["month"]["pageviews"] == 1
    assert [p["path"] for p in body["top_pages"]] == ["/"]
