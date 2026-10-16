"""Wins as evidence: evidence_url validation, archiver interface, hash chain, Sheets gate."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol
from urllib.parse import urlparse

log = logging.getLogger("scouter.wins")

CRITERION_HINTS_PATH = Path(__file__).resolve().parents[1] / "data" / "criterion_hints.json"
_CH = json.loads(CRITERION_HINTS_PATH.read_text(encoding="utf-8"))
# Researcher's file is the source of truth: allowed values = keys under `values`.
CRITERION_HINTS: tuple[str, ...] = tuple(_CH["values"])
DEFAULT_HINT_BY_WIN_TYPE: dict[str, str] = dict(_CH["default_by_win_type"])


def default_criterion_hint(win_type: Optional[str]) -> str:
    return DEFAULT_HINT_BY_WIN_TYPE.get(win_type or "", "none")
GENESIS = "GENESIS"
WAYBACK_SAVE = "https://web.archive.org/save/"
# Fields hashed into row_hash (everything in the row except row_hash itself).
HASHED_FIELDS = ("date", "slug", "outlet", "asset_id", "source_id", "win_type", "card_id", "note",
                 "evidence_url", "archive_url", "criterion_hint", "is_test", "prev_hash")


SCOUTER_PORTS = frozenset({8710, 5173})


def _ip_literal(host: str):
    """Parse an IP literal, including decimal/hex/octal IPv4 forms (no DNS)."""
    h = host.strip("[]")
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        pass
    if re.fullmatch(r"[0-9a-fA-FxX.]+", h) and re.search(r"\d", h):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(h))
        except OSError:
            return None
    return None


def _app_hosts() -> set[str]:
    return {x.strip().lower() for x in os.environ.get("MS_APP_HOSTS", "").split(",") if x.strip()}


def evidence_url_problem(u: Any) -> Optional[str]:
    """None when u is a public https link; else a short plain reason. No DNS lookups."""
    if not isinstance(u, str) or not u.strip():
        return "the link is empty"
    u = u.strip()
    if any(ch.isspace() for ch in u):
        return "the link has spaces in it"
    try:
        p = urlparse(u)
        port = p.port
    except ValueError:
        return "the link isn't a valid web address"
    if p.scheme.lower() != "https":
        return "only https:// links are accepted"
    if "@" in p.netloc:
        return "links with a user name or password aren't accepted"
    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        return "the link has no host"
    if host == "localhost" or host.endswith(".localhost"):
        return "links to this computer aren't accepted"
    if host in _app_hosts():
        return "links to the scouter itself aren't accepted"
    ip = _ip_literal(host)
    if ip is not None:
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
            return "links to private or local network addresses aren't accepted"
    elif "." not in host:
        return "the link needs a public domain name"
    if port in SCOUTER_PORTS and (ip is not None or "." not in host):
        return "links to the scouter itself aren't accepted"
    return None


Resolver = Callable[[str], list[str]]


def getaddrinfo_resolver(host: str) -> list[str]:
    """Default resolver: every address the host resolves to (A + AAAA)."""
    return sorted({info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})


def _blocked_ip(ip) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_unspecified or ip.is_multicast or ip.is_reserved)


def resolve_problem(u: str, resolver: Optional[Resolver] = None) -> Optional[tuple[str, str]]:
    """Resolve the link's host at confirm time. (code, reason) on refusal, else None.

    No redirect following: only the host as written is checked.
    """
    host = (urlparse(u.strip()).hostname or "").lower().rstrip(".")
    if _ip_literal(host) is not None:
        return None  # literal already checked by evidence_url_problem
    try:
        addrs = list((resolver or getaddrinfo_resolver)(host))
    except Exception:
        return ("evidence_url_unresolvable", "the host couldn't be resolved")
    if not addrs:
        return ("evidence_url_unresolvable", "the host couldn't be resolved")
    for a in addrs:
        try:
            ip = ipaddress.ip_address(str(a).split("%")[0])
        except ValueError:
            return ("evidence_url_unresolvable", "the host resolved to an unreadable address")
        if _blocked_ip(ip):
            return ("evidence_url_invalid", "resolves_private")
    return None


def check_link(u: Any, resolver: Optional[Resolver] = None) -> Optional[tuple[str, str]]:
    """Full confirm-time check: static rules, then DNS. (code, reason) or None."""
    problem = evidence_url_problem(u)
    if problem:
        return ("evidence_url_invalid", problem)
    return resolve_problem(u, resolver)


def valid_public_url(u: Any) -> bool:
    return evidence_url_problem(u) is None


def wayback_save_url(evidence_url: str) -> str:
    return WAYBACK_SAVE + evidence_url.strip()


class Archiver(Protocol):
    def archive(self, evidence_url: str) -> Optional[str]:
        """Return an archive URL, or None / raise on failure."""


class WaybackArchiver:
    """Live: asks the Wayback Machine to save the page. Used only on a real user confirm."""

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    def archive(self, evidence_url: str) -> Optional[str]:
        url = wayback_save_url(evidence_url)
        req = urllib.request.Request(url, headers={"User-Agent": "market-scouter/0 (personal evidence log)"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
            loc = r.geturl()
        return loc if loc and "web.archive.org/web/" in loc else url


class NullArchiver:
    """No network: records the Wayback save URL form without fetching it."""

    def archive(self, evidence_url: str) -> Optional[str]:
        return wayback_save_url(evidence_url)


def default_archiver() -> Archiver:
    mode = os.environ.get("MS_ARCHIVER", "live")
    return NullArchiver() if mode == "off" else WaybackArchiver()


def run_archive(archiver: Archiver, evidence_url: str, provided: Optional[str]) -> tuple[Optional[str], str]:
    """(archive_url, archive_status). Never raises."""
    if provided:
        if valid_public_url(provided):
            return provided.strip(), "provided"
        return None, "failed"
    try:
        got = archiver.archive(evidence_url)
    except Exception as e:  # network, HTTP, timeout
        log.warning("archive_failed: %s (%s)", evidence_url, e)
        return None, "failed"
    return (got, "archived") if got else (None, "failed")


def row_hash(row: Mapping[str, Any]) -> str:
    canon = json.dumps({k: row.get(k) for k in HASHED_FIELDS}, sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def verify_chain(rows: Iterable[Mapping[str, Any]]) -> dict:
    """Rows in log order. ok=False with the first broken index if anything was edited/removed/reordered."""
    prev = GENESIS
    n = 0
    for i, r in enumerate(rows):
        if r.get("prev_hash") != prev:
            return {"ok": False, "index": i, "reason": "prev_hash_mismatch", "count": n}
        if row_hash(r) != r.get("row_hash"):
            return {"ok": False, "index": i, "reason": "row_hash_mismatch", "count": n}
        prev = r["row_hash"]
        n += 1
    return {"ok": True, "count": n, "head": prev}


def chain_head(rows: Iterable[Mapping[str, Any]]) -> str:
    head = GENESIS
    for r in rows:
        head = r.get("row_hash") or head
    return head
