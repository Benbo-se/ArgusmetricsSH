"""
Request/network helpers.

Centralizes client-IP extraction so X-Forwarded-For is only trusted when the
immediate peer is a configured trusted proxy. Spoofable XFF was previously used
as a rate-limit key and visitor identifier, enabling trivial bypass/poisoning.
"""
import ipaddress
import logging
from typing import List

from fastapi import Request

from app.config import settings

logger = logging.getLogger(__name__)


def _trusted_networks() -> List["ipaddress._BaseNetwork"]:
    nets = []
    for item in (settings.TRUSTED_PROXIES or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid TRUSTED_PROXIES entry: %r", item)
    return nets


def get_client_ip(request: Request) -> str:
    """
    Return the best-effort real client IP.

    X-Forwarded-For is honored ONLY when the socket peer is in TRUSTED_PROXIES;
    in that case we walk hops from the right and return the first one that is not
    itself a trusted proxy. With no trusted proxies configured (default), the
    socket peer is used and client-supplied headers are ignored.
    """
    peer = request.client.host if request.client else None
    trusted = _trusted_networks()

    if peer and trusted:
        try:
            peer_ip = ipaddress.ip_address(peer)
        except ValueError:
            peer_ip = None
        if peer_ip is not None and any(peer_ip in n for n in trusted):
            xff = request.headers.get("X-Forwarded-For", "")
            hops = [h.strip() for h in xff.split(",") if h.strip()]
            for hop in reversed(hops):
                try:
                    hop_ip = ipaddress.ip_address(hop)
                except ValueError:
                    continue
                if not any(hop_ip in n for n in trusted):
                    return hop

    return peer or "unknown"
