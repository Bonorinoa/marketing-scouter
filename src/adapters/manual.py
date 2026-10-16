"""manual.paste — always-works happy path. Read-only URL → Candidate."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from ..models import AdapterId, Candidate, Outlet, TStatus

_X_HOSTS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com", "mobile.twitter.com"}
_LI_HOSTS = {"linkedin.com", "www.linkedin.com", "lnkd.in"}


def _cand_id(url: str) -> str:
    return "cand_" + hashlib.sha256(url.encode()).hexdigest()[:12]


def infer_outlet(url: str, outlet_hint: Outlet | None = None) -> Outlet:
    if outlet_hint:
        return outlet_hint
    host = urlparse(url).netloc.lower()
    if host in _X_HOSTS or host.endswith(".x.com"):
        return Outlet.X
    if host in _LI_HOSTS or "linkedin.com" in host:
        return Outlet.LINKEDIN
    # default X for ambiguous paste in prototype
    return Outlet.X


def _guess_snippet(url: str, outlet: Outlet, title_hint: str | None) -> str:
    if title_hint:
        return title_hint
    path = urlparse(url).path
    # Extract status id or post slug as placeholder snippet
    m = re.search(r"/status/(\d+)", path)
    if m:
        return (
            f"X thread status/{m.group(1)} — pasted for scouting. "
            "Topic cues: LLM cultural bias WEIRD synthetic subjects."
        )
    if outlet == Outlet.LINKEDIN:
        return (
            "LinkedIn post (pasted) — construct validity / LLM measurement discussion. "
            "Looking for substantive method comments."
        )
    return f"Pasted URL opportunity: {url}"


class ManualPasteAdapter:
    id = AdapterId.MANUAL_PASTE

    def discover(
        self,
        urls: list[str],
        *,
        outlet_hint: Outlet | None = None,
        title_hint: str | None = None,
        author: str | None = None,
        age_hours: float | None = 12.0,
        reply_count: int | None = None,
        quote_count: int | None = None,
        comment_count: int | None = None,
        like_count: int | None = None,
    ) -> list[Candidate]:
        return [
            self.fetch(
                u,
                outlet_hint=outlet_hint,
                title_hint=title_hint,
                author=author,
                age_hours=age_hours,
                reply_count=reply_count,
                quote_count=quote_count,
                comment_count=comment_count,
                like_count=like_count,
            )
            for u in urls
            if u and u.strip()
        ]

    def fetch(
        self,
        url: str,
        *,
        outlet_hint: Outlet | None = None,
        title_hint: str | None = None,
        author: str | None = None,
        age_hours: float | None = 12.0,
        reply_count: int | None = None,
        quote_count: int | None = None,
        comment_count: int | None = None,
        like_count: int | None = None,
    ) -> Candidate:
        url = url.strip()
        outlet = infer_outlet(url, outlet_hint)
        created = None
        if age_hours is not None:
            created = datetime.now(timezone.utc) - timedelta(hours=float(age_hours))

        t_status = TStatus.UNKNOWN
        if outlet == Outlet.X and (reply_count is not None or quote_count is not None):
            t_status = TStatus.OK
        if outlet == Outlet.LINKEDIN and comment_count is not None:
            t_status = TStatus.OK

        return Candidate(
            candidate_id=_cand_id(url),
            adapter=AdapterId.MANUAL_PASTE,
            outlet=outlet,
            url=url,
            title_or_snippet=_guess_snippet(url, outlet, title_hint),
            author=author,
            created_at=created,
            reply_count=reply_count if outlet == Outlet.X else None,
            quote_count=quote_count if outlet == Outlet.X else None,
            comment_count=comment_count if outlet == Outlet.LINKEDIN else None,
            like_count=like_count,  # info only
            raw_meta={"source": "manual.paste"},
            T_status=t_status,
        )

    @property
    def capabilities(self) -> dict:
        return {
            "discover": "urls",
            "traction": "optional user-supplied; likes never scored",
            "posts": False,
        }
