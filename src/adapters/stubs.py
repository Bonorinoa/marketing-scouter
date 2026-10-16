"""Stub adapters for x.seed, li.google_site, li.paste — discover returns empty / URL shells."""

from __future__ import annotations

from ..models import AdapterId, Candidate, Outlet, TStatus
from .manual import ManualPasteAdapter, infer_outlet


class XSeedAdapter:
    """Curated Fit-slug queries → open-search URL shells (no live API in v0)."""

    id = AdapterId.X_SEED

    def discover(self, query: str, *, slug: str | None = None) -> list[Candidate]:
        # v0: return a single search-URL shell so UI can deep-link to public search
        q = query.strip()
        if not q:
            return []
        from urllib.parse import quote_plus

        url = f"https://x.com/search?q={quote_plus(q)}&src=typed_query&f=live"
        return [
            Candidate(
                adapter=AdapterId.X_SEED,
                outlet=Outlet.X,
                url=url,
                title_or_snippet=f"X public search seed: {q}"
                + (f" (slug={slug})" if slug else ""),
                author=None,
                created_at=None,
                T_status=TStatus.UNKNOWN,
                raw_meta={"query": q, "slug": slug, "stub": True},
            )
        ]

    def fetch(self, url: str) -> Candidate:
        return ManualPasteAdapter().fetch(url, outlet_hint=Outlet.X)

    @property
    def capabilities(self) -> dict:
        return {"discover": "query→search URL", "traction": "none until fetch", "posts": False}


class LiGoogleSiteAdapter:
    id = AdapterId.LI_GOOGLE_SITE

    def discover(self, query: str, *, slug: str | None = None) -> list[Candidate]:
        q = query.strip()
        if not q:
            return []
        from urllib.parse import quote_plus

        # Prefer site:linkedin.com/posts fragment if missing
        if "site:linkedin.com" not in q.lower():
            q = f"site:linkedin.com/posts {q}"
        url = f"https://www.google.com/search?q={quote_plus(q)}"
        return [
            Candidate(
                adapter=AdapterId.LI_GOOGLE_SITE,
                outlet=Outlet.LINKEDIN,
                url=url,
                title_or_snippet=f"LI SERP seed: {q}"
                + (f" (slug={slug})" if slug else ""),
                T_status=TStatus.UNKNOWN,
                raw_meta={"query": q, "slug": slug, "stub": True},
            )
        ]

    def fetch(self, url: str) -> Candidate:
        return ManualPasteAdapter().fetch(url, outlet_hint=Outlet.LINKEDIN)

    @property
    def capabilities(self) -> dict:
        return {"discover": "SERP links", "traction": "usually unknown", "posts": False}


class LiPasteAdapter:
    id = AdapterId.LI_PASTE

    def __init__(self):
        self._inner = ManualPasteAdapter()

    def discover(self, urls: list[str], **kwargs) -> list[Candidate]:
        kwargs = dict(kwargs)
        kwargs["outlet_hint"] = kwargs.get("outlet_hint") or Outlet.LINKEDIN
        return self._inner.discover(urls, **kwargs)

    def fetch(self, url: str, **kwargs) -> Candidate:
        # Force LI tagging even if host ambiguous
        kwargs = dict(kwargs)
        hint = kwargs.pop("outlet_hint", None) or Outlet.LINKEDIN
        outlet = infer_outlet(url, hint)
        return self._inner.fetch(url, outlet_hint=outlet, **kwargs)

    @property
    def capabilities(self) -> dict:
        return {"discover": "urls", "traction": "maybe comment_count", "posts": False}
