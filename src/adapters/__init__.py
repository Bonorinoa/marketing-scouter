"""Source adapters — read/seed/paste only. Never post."""

from .manual import ManualPasteAdapter
from .stubs import XSeedAdapter, LiGoogleSiteAdapter, LiPasteAdapter

ADAPTERS = {
    "manual.paste": ManualPasteAdapter(),
    "x.seed": XSeedAdapter(),
    "li.google_site": LiGoogleSiteAdapter(),
    "li.paste": LiPasteAdapter(),
}


def get_adapter(adapter_id: str):
    if adapter_id not in ADAPTERS:
        raise KeyError(f"Unknown adapter: {adapter_id}")
    return ADAPTERS[adapter_id]
