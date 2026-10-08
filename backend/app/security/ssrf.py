"""SSRF protection for user-supplied targets (websites, API specs, API base URLs).

The same policy is enforced again inside the Playwright engine (engine/src/guard.ts)
for every request the browser or API client makes, so a page that redirects or
loads sub-resources from internal addresses is blocked at runtime too.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from ..config import get_settings

BLOCKED_HOSTNAMES = {"metadata.google.internal", "metadata", "instance-data"}


class TargetNotAllowed(ValueError):
    pass


def _ip_blocked(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


def check_url(url: str, *, resolve: bool = True) -> str:
    """Validate ``url``; returns the hostname or raises TargetNotAllowed."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise TargetNotAllowed("Only http and https URLs can be tested")
    host = (parts.hostname or "").lower()
    if not host:
        raise TargetNotAllowed("The URL has no host name")
    if parts.username or parts.password:
        raise TargetNotAllowed("Put credentials in environment secrets, not in the URL")
    if host in get_settings().allowed_private_host_set:
        return host
    if host in BLOCKED_HOSTNAMES or host.endswith(".internal") or host == "localhost":
        raise TargetNotAllowed(f"Host {host} is on the blocked list")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _ip_blocked(literal):
            raise TargetNotAllowed(f"Address {host} is in a private or reserved range")
        return host
    if resolve:
        try:
            infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
        except socket.gaierror as exc:
            raise TargetNotAllowed(f"Host {host} could not be resolved") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if _ip_blocked(ip):
                raise TargetNotAllowed(f"Host {host} resolves to restricted address {ip}")
    return host
