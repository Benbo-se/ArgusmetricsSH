"""Values that end up in a redirect address go in encoded.

A redirect is built from a fixed path and a value that came from the request.
The value must stay one value: it may not add a parameter of its own or
change where the address points.
"""


def test_the_range_stays_one_value_in_the_public_dashboard_redirect(client, shared_website):
    token = shared_website["share_token"]

    answer = client.post(
        f"/public/{token}",
        params={"range": "7d&next=//elsewhere.example"},
        data={"password": "anything"},
        follow_redirects=False,
    )

    assert answer.status_code == 303
    assert answer.headers["location"] == f"/public/{token}?range=7d%26next%3D%2F%2Felsewhere.example"


def test_an_ordinary_range_is_unchanged(client, shared_website):
    token = shared_website["share_token"]

    answer = client.post(
        f"/public/{token}", params={"range": "30d"}, data={"password": "anything"},
        follow_redirects=False,
    )

    assert answer.headers["location"] == f"/public/{token}?range=30d"
