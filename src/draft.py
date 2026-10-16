"""Channel-shaped drafts — suggests only, never posts.

One door per thread; never mix jargon; never CTA.
EconLLM = claim-source door label only (not org ownership).
Augusto-civic = provincial / journalism voice; no lab plug.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .fit import claim_for_slug
from .models import InventoryAsset, MoveType, Outlet, ScoredCard, VoiceDoor

_VOICE_PATH = Path(__file__).resolve().parent.parent / "data" / "voice_seeds.json"

_FALLBACK_SEEDS = {
    VoiceDoor.ECONLLM: (
        "One thing our SCA non-WEIRD pilots keep showing: when you swap WEIRD "
        "priors for local cultural agents, the ‘empty’ finding isn’t noise — "
        "it’s the measurement layer telling you the survey never asked the right question."
    ),
    VoiceDoor.AUGUSTO_CIVIC: (
        "En Tucumán el problema no es falta de datos, es falta de verificación "
        "en contexto: si la nota no nombra la fuente local y el recorte temporal, "
        "Community Notes no alcanza — hace falta el mismo rigor que pedimos en un paper."
    ),
}


@lru_cache(maxsize=1)
def load_voice_seeds() -> dict:
    if _VOICE_PATH.exists():
        return json.loads(_VOICE_PATH.read_text(encoding="utf-8"))
    return {"doors": {}}


CLAIM_ES_DRAFT: dict[str, str] = {}  # op-ed outlet only; filled when an op-ed outlet exists

_TERMINAL = ".!?…"
_CLOSERS = "\"'”’»)]"


def _end_sentence(text: str) -> str:
    """The claim must end with terminal punctuation before the next sentence is joined on."""
    t = (text or "").rstrip()
    core = t.rstrip(_CLOSERS)
    return t if not t or (core and core[-1] in _TERMINAL) else t + "."


CIVIC_EN_SEED = (
    "In Tucumán the problem isn't a lack of data, it's a lack of checking in context: "
    "if a story doesn't name its local source and time frame, Community Notes isn't enough. "
    "We need the same care we ask of a research paper."
)


SOCIAL_OUTLETS = frozenset({"x", "linkedin"})


def card_is_oped(outlet, asset: InventoryAsset | None) -> bool:
    """Spanish is decided by the OUTLET: X/LinkedIn cards are always English;
    only a real op-ed outlet on an op-ed asset is Spanish (Augusto decision 2026-10-09)."""
    o = getattr(outlet, "value", outlet)
    return o not in SOCIAL_OUTLETS and is_oped(asset)


def is_oped(asset: InventoryAsset | None) -> bool:
    """Spanish only for op-eds to Argentine outlets (Augusto decision 2026-10-08)."""
    return bool(asset and asset.door_archive.value == VoiceDoor.AUGUSTO_CIVIC.value
                and (asset.surface == "carta" or asset.oped_status is not None))


def voice_seed(door: VoiceDoor) -> str:
    data = load_voice_seeds()
    doors = data.get("doors") or {}
    entry = doors.get(door.value) or {}
    seed = entry.get("seed")
    if seed:
        return seed
    return _FALLBACK_SEEDS[door]


def _primary_claim(card: ScoredCard, asset: InventoryAsset | None) -> str:
    """Every built-in path that leads with or joins the claim gets it via here: always a finished sentence."""
    if asset and asset.one_line_claim:
        return _end_sentence(asset.one_line_claim.strip())
    if card.slugs:
        return _end_sentence(claim_for_slug(card.slugs[0]))
    return "a specific finding from inventory"


def _asset_url(asset: InventoryAsset | None) -> str | None:
    if asset and asset.url:
        return asset.url
    return None


def _caveat(asset: InventoryAsset | None) -> str | None:
    c = (asset.caveat or "").strip() if asset else ""
    return c or None


_POINT_STOP = frozenset("""a an the and or but of to in on at by for with from as is are was were be been being can could
should would will may might must do does did not no only that this these those it its their there where which who
whom whose what when how than then so such into over under about via per our we you your i my me he she they them
his her us just like really very also yes yeah here here's there's it's that's i'm we're you're they're don't
doesn't isn't aren't can't won't if because while just still even ever get got make made say said says think
thought know new now today one ran lol lmao omg wow""".split())
_POINT_VERB = frozenset("""hold holds held look looks looked work works worked matter matters went go goes show shows showed
need needs seem seems keep keeps went went make makes help helps fail fails replace replacing replaces up out off down""".split())
_WORD = r"[A-Za-z0-9][A-Za-z0-9'’\-]*"


def _post_point(post: str, max_words: int = 5) -> str:
    """The post's point in its own few words (unquoted): the longest run of content words in the
    first sentence, so the opener can answer it. Empty when nothing usable is there."""
    import re as _re
    t = _re.sub(r"https?://\S+", " ", post or "")
    t = _re.sub(r"(?:^|\s)[@#]\w+", " ", t)
    t = _re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""
    first = _re.split(r"(?<=[.!?…])\s+|\n", t, maxsplit=1)[0]
    toks = [(m.group(0), m.start()) for m in _re.finditer(_WORD, first)]
    best: list = []
    run: list = []
    for w, pos in toks + [("", -1)]:
        clean = w.strip("'’-")
        if clean and clean.lower().replace("’", "'") not in _POINT_STOP and len(clean) >= 2:
            run.append((clean, pos))
            continue
        if len(run) > len(best):
            best = run
        run = []
    # a run of content words often swallows a verb ("world values map hold up"): cut at the first one
    cut = next((i for i, (w, _p) in enumerate(best) if i > 0 and (w.lower() in _POINT_VERB or (
        "-" not in w and len(w) > 4 and w.lower().endswith(("ed", "ing"))))), None)
    best = best[:cut] if cut else best
    if not best:
        return ""
    best = best[-max_words:]
    words = [w for w, _ in best]
    w0 = best[0][0]
    proper = len(words) > 1 and words[1][:1].isupper()  # "Community Notes", "Artificial Societies"
    if first.lstrip().startswith(w0) and not proper and not w0.isupper() and w0[:1].isupper():
        words[0] = w0[:1].lower() + w0[1:]   # capital only from sentence start
    return " ".join(words)


def _answer_opener(post: str, door: VoiceDoor | None = None) -> str:
    """First line answers the post's point (Designer P1 #6): never "Re:", never a quote of their text."""
    point = _post_point(post)
    lead = f"On {point}," if point else "On that point,"
    if door == VoiceDoor.AUGUSTO_CIVIC:
        return f"{lead} that's where verification matters."
    if door == VoiceDoor.ECONLLM:
        return f"{lead} it's worth checking against the evidence."
    return f"{lead} one thing to add."


def _engage_post(post: str, budget: int = 110) -> str:
    """Opening sentence that answers the post (no Re:, no quote-cue)."""
    out = _answer_opener(post)
    return out if len(out) <= budget else "On that point, one thing to add."



def _slug_tuned_seed(card: ScoredCard, asset: InventoryAsset | None) -> str:
    """Seed body, ending with the asset's caveat verbatim when it has one."""
    body = _slug_tuned_body(card, asset)
    cav = _caveat(asset)
    if cav and cav.lower() not in body.lower():
        body = f"{body.rstrip()} {cav}"
    return body


def _fit_x(body: str, claim: str, caveat: str | None, budget: int) -> str:
    """Fit X budget: keep the claim and the caveat verbatim; drop other middle
    sentences, last first. If claim+caveat still don't fit, return the body
    untouched so the gate blocks it as too_long. Never truncates."""
    import re as _re
    body = body.strip()
    if len(body) <= budget:
        return body
    core = body
    if caveat and core.endswith(caveat):
        core = core[: -len(caveat)].rstrip()
    else:
        caveat = None
    parts = [p for p in _re.split(r"(?<=[.!?])\s+", core) if p]
    # Protect the claim wherever it sits (P2 #7: claim may follow a post opener / pivot)
    claim_i = next((i for i, p in enumerate(parts) if claim and (
        p == claim or p.startswith(claim) or claim.startswith(p.rstrip(".")))), None)
    if claim and claim_i is None:
        # claim text may be embedded without being its own sentence — keep whole core
        head, middle = (parts[0] if parts else ""), parts[1:]
        protected = []
    elif claim and claim_i is not None:
        head = parts[0] if claim_i > 0 else parts[claim_i]
        protected = [parts[claim_i]] if claim_i > 0 else []
        middle = [p for i, p in enumerate(parts) if i != 0 and i != claim_i]
        if claim_i == 0:
            middle = parts[1:]
            protected = []
    else:
        head, middle, protected = (parts[0] if parts else ""), parts[1:], []
    tail = [caveat] if caveat else []
    while middle and len(" ".join([x for x in [head, *protected, *middle, *tail] if x])) > budget:
        middle.pop()
    # If still over: replace a long opener with a minimal cue so the claim is never first
    pieces = [x for x in [head, *protected, *middle, *tail] if x]
    if len(" ".join(pieces)) > budget and protected and head != protected[0]:
        cue = "On that point."
        pieces = [x for x in [cue, *protected, *middle, *tail] if x]
        if len(" ".join(pieces)) > budget:
            pieces = [x for x in [*protected, *middle, *tail] if x]
    out = " ".join(pieces)
    return out if len(out) <= budget else body


def _slug_tuned_body(card: ScoredCard, asset: InventoryAsset | None) -> str:
    """Prefer marketing voice seed; lightly tune with claim when slug-specific."""
    base = voice_seed(card.voice_door)
    if card.voice_door == VoiceDoor.AUGUSTO_CIVIC and not card_is_oped(card.outlet, asset):
        base = CIVIC_EN_SEED
    claim = _primary_claim(card, asset)
    # For non-SCA EconLLM assets, keep door voice but lead with the asset claim
    if card.voice_door == VoiceDoor.ECONLLM:
        if card.slugs and card.slugs[0].startswith("sca"):
            return base
        if card.slugs and any(s.startswith("cvp") for s in card.slugs):
            pivot = "Measure first."
            if _caveat(asset):
                return f"{pivot} {claim}"  # caveat appended in _slug_tuned_seed
            return f"{pivot} {claim} Check the measure before claiming cause and effect."
        if "gpt4o-weird" in (card.slugs or []):
            return f"A WVS-style bias signal to stress. {claim}"
        if any(
            s in (card.slugs or [])
            for s in ("complexity-policy", "econ-ai-cas", "abm-organizations")
        ):
            return (
                f"Feedback and emergence beat one-shot optimization when the system is adaptive. {claim}"
            )
        return f"{base}\n\n{claim}"
    # Civic: short pivot first (never lead with the claim), then the claim. Full seed is too long for X.
    if card.voice_door == VoiceDoor.AUGUSTO_CIVIC and card.slugs:
        if card_is_oped(card.outlet, asset):
            cl = _end_sentence(CLAIM_ES_DRAFT.get(card.slugs[0], claim_for_slug(card.slugs[0])))
            return f"{base} {cl}"
        cl = _end_sentence(claim_for_slug(card.slugs[0]))
        pivot = "Verification with named local context is the scarce bit."
        return f"{pivot} {cl}"
    return base


def _x_reply_on_post(card: ScoredCard, asset: InventoryAsset | None, post: str) -> str:
    """Post-first X reply: short cue → claim → caveat. Keeps claim+caveat under the X budget."""
    claim = _primary_claim(card, asset)
    cav = _caveat(asset)
    # First sentence answers their point in our voice (no "Re:", no quoted cue); claim comes second
    opener = _answer_opener(post, card.voice_door)
    body = f"{opener} {claim}"
    if cav and cav.lower() not in body.lower():
        body = f"{body} {cav}"
    url = _asset_url(asset)
    from .voice_gate import URL_WEIGHT, X_MAX
    attach = (card.voice_door == VoiceDoor.ECONLLM and url) or (
        card.voice_door == VoiceDoor.AUGUSTO_CIVIC and url and asset and asset.oped_status)
    budget = X_MAX - ((URL_WEIGHT + 2) if attach else 0)
    body = _fit_x(body, claim, cav, budget)
    if attach and url:
        body = f"{body}\n\n{url}"
    return body.strip()


def draft_x_short(card: ScoredCard, asset: InventoryAsset | None,
                  post_text: str = "") -> str:
    """X: short, one concrete add, optional durable URL. No CTA. Opens on the post when given."""
    if (post_text or "").strip():
        return _x_reply_on_post(card, asset, post_text.strip())
    body = _slug_tuned_seed(card, asset)
    url = _asset_url(asset)
    # Fit the gate's X limit (links weigh URL_WEIGHT): drop whole trailing sentences, never cut mid-word.
    from .voice_gate import URL_WEIGHT, X_MAX
    attach = (card.voice_door == VoiceDoor.ECONLLM and url) or (
        card.voice_door == VoiceDoor.AUGUSTO_CIVIC and url and asset and asset.oped_status)
    budget = X_MAX - ((URL_WEIGHT + 2) if attach else 0)
    body = _fit_x(body, _primary_claim(card, asset), _caveat(asset), budget)
    if card.voice_door == VoiceDoor.ECONLLM and url:
        body = f"{body}\n\n{url}"
    # Civic: no lab URL flex unless it's a public civic piece
    if card.voice_door == VoiceDoor.AUGUSTO_CIVIC and url and asset and asset.oped_status:
        body = f"{body}\n\n{url}"
    return body.strip()


def draft_li_substantive(card: ScoredCard, asset: InventoryAsset | None) -> str:
    """LinkedIn: claim → bullets → limitation → invite reply. No CTA / congrats."""
    seed = _slug_tuned_seed(card, asset)
    claim = _primary_claim(card, asset)
    url = _asset_url(asset)

    if card.voice_door == VoiceDoor.AUGUSTO_CIVIC and not card_is_oped(card.outlet, asset):
        return "\n".join([seed, "", f"Claim: {claim}",
                          "• Cheap AI text is not the same as checked local context.",
                          "• Limit: global notes don't replace a named source and a date range.",
                          *([f"• Caveat: {_caveat(asset)}"] if _caveat(asset) else []), "",
                          "How is your newsroom checking stories in context?"])
    if card.voice_door == VoiceDoor.AUGUSTO_CIVIC:
        lines = [
            seed,
            "",
            f"• Afirmación: {claim}",
            "• Diseño: generación barata ≠ contexto local verificado",
            "• Límite: Notes globales no sustituyen fuente + recorte temporal",
            "",
            "¿Cómo están resolviendo la verificación en contexto en sus redacciones?",
        ]
        return "\n".join(lines)

    lines = [
        seed,
        "",
        f"Claim: {claim}",
        "",
        "• Design: treat the set of possible measures as a range of answers, not a single score.",
        "• Fragility: results depend on which settings you pick, so test them before saying X causes Y.",
        "• Limitation: external validity still needs human data where it exists.",
        *([f"• Caveat: {_caveat(asset)}"] if _caveat(asset) else []),
        "",
        "Which assumptions are you stating openly in your setup?",
    ]
    text = "\n".join(lines)
    if url:
        text += f"\n\n{url}"
    return text


def _with_post_opener(body: str, post: str) -> str:
    """Put a post cue first so the opening sentence is about their thread, not our claim."""
    post = (post or "").strip()
    if not post:
        return body
    opener = _engage_post(post)
    # Avoid duplicating if body already opens on the post
    if body.lstrip().startswith(opener):
        return body
    return f"{opener} {body.lstrip()}"


def shape_draft(card: ScoredCard, asset: InventoryAsset | None = None,
                post_text: str | None = None) -> str:
    """Produce channel-shaped draft. One door; never mix; never CTA.

    When post text is available (title_or_snippet or post_text), the reply opens on
    the post (Designer P2 #7), then brings in the claim — never as a first-sentence restatement.
    """
    post = (post_text if post_text is not None else (card.title_or_snippet or "")).strip()
    if card.outlet == Outlet.X:
        if card.move_type == MoveType.QUOTE:
            seed = _with_post_opener(_slug_tuned_seed(card, asset), post)
            url = _asset_url(asset)
            from .voice_gate import URL_WEIGHT, X_MAX
            if _caveat(asset):  # never cut a caveat; gate blocks too_long instead
                line = _fit_x(seed, _primary_claim(card, asset), _caveat(asset),
                              X_MAX - ((URL_WEIGHT + 1) if (card.voice_door == VoiceDoor.ECONLLM and url) else 0))
            else:
                line = seed if len(seed) < 260 else seed[:257] + "…"
            if card.voice_door == VoiceDoor.ECONLLM and url:
                line = f"{line}\n{url}"
            return line
        return draft_x_short(card, asset, post_text=post)
    if card.move_type == MoveType.ORIGINAL:
        return _with_post_opener(draft_li_substantive(card, asset), post) if post else draft_li_substantive(card, asset)
    body = draft_li_substantive(card, asset)
    return _with_post_opener(body, post) if post else body
