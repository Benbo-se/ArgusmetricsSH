#!/usr/bin/env python3
"""Serve the marketing site the way nginx does in production.

nginx.prod.conf resolves a request with:

    try_files $uri $uri.html $uri/ =404;

so /contact is served from contact.html and /docs/ from docs/index.html.
Python's http.server does none of that: it 404s on /contact and the site looks
broken in exactly the places a visitor would actually click.

That difference cost a CI failure. The end-to-end suite fetches the clean URLs
because the site really does serve them, and the test was right while the
server under it was not. Same file for CI and for previewing locally, so the
two cannot drift apart again.

    python3 site/serve.py [port]
"""
import functools
import http.server
import os
import sys


class TryFilesHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler plus the .html fallback nginx applies."""

    def translate_path(self, path):
        resolved = super().translate_path(path)

        if os.path.isdir(resolved):
            index = os.path.join(resolved, "index.html")
            return index if os.path.exists(index) else resolved

        if not os.path.exists(resolved):
            with_html = resolved + ".html"
            if os.path.exists(with_html):
                return with_html

        return resolved

    def end_headers(self):
        # Never cache while previewing: an edited page that still shows the old
        # version wastes more time than it saves.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if os.environ.get("SERVE_QUIET"):
            return
        super().log_message(fmt, *args)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    root = os.path.dirname(os.path.abspath(__file__))

    handler = functools.partial(TryFilesHandler, directory=root)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Serving {root} on http://127.0.0.1:{port} with nginx-style try_files")
        server.serve_forever()


if __name__ == "__main__":
    main()
