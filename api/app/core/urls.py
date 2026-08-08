import ipaddress
import os
import socket
from urllib.parse import urlsplit


def validate_render_node_url(url: str, *, resolve_dns: bool = True) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Render node URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("Render node URL must not contain credentials")
    hostname = parsed.hostname.lower().rstrip(".")
    if "%" in hostname:
        raise ValueError("Render node URL contains an invalid host")
    if hostname in allowed_render_node_hosts():
        return url.rstrip("/")
    if hostname == "localhost" or hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise ValueError("Render node URL points to a private network host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if not resolve_dns:
            return url.rstrip("/")
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(hostname, parsed.port)
            }
        except socket.gaierror as exc:
            raise ValueError("Render node host could not be resolved") from exc
        if not addresses:
            raise ValueError("Render node host could not be resolved")
    else:
        addresses = {address}
    if any(is_blocked_address(address) for address in addresses):
        raise ValueError("Render node URL points to a private network address")
    return url.rstrip("/")


def allowed_render_node_hosts() -> set[str]:
    return {
        host.strip().lower().rstrip(".")
        for host in os.getenv("COMFYUI_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }


def is_blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )
