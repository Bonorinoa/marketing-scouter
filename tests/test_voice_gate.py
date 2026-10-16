import pytest
from src.voice_gate import check_draft, DraftCard, CODES, x_length

CARTA = dict(outlet="x", door="Augusto-civic",
             slugs=["ai-society-governance"],
             asset_title="Adepa / La Gaceta carta — verification and local context",
             asset_claim="Generation and amplification are cheap; verification and locally named context are scarce public goods.")
SCA = dict(outlet="x", door="EconLLM", slugs=["sca-nonweird"],
           asset_title="LLMs Model Non-WEIRD Populations", asset_url="https://arxiv.org/abs/2501.06834",
           slug_claims={"sca-nonweird": "LLM synthetic cultural agents can qualitatively track non-WEIRD experimental behavior where human data exist"})

# Own-words paraphrases: < 60% of the claim's content words (claim_overlap, 2026-10-14)
GOOD_CARTA = ("AI governance is not a choice between ban and hype. The real question is the information "
              "architecture: making posts costs nothing now, so checking them and naming local context is what we lack.")
GOOD_SCA = ("Before you field a hard-to-reach sample, run a cheap pilot: synthetic agents roughly follow "
            "non-WEIRD lab behavior when there are human results to check against. "
            "https://arxiv.org/abs/2501.06834")
ES_CARTA = ("La generación de contenido es barata, pero la verificación y el contexto local son bienes "
            "públicos escasos. No se trata de prohibir la IA sino de diseñar las reglas.")


def codes(r):
    return {x["code"] for x in r.reasons}


def test_full_pass_civic_x_carta_ai_society_governance():
    r = check_draft(GOOD_CARTA, CARTA)
    assert r.ok, r.reasons


def test_pass_econllm_x_with_asset_link():
    assert check_draft(GOOD_SCA, SCA).ok


def test_accepts_dataclass_card():
    assert check_draft(GOOD_CARTA, DraftCard(**CARTA)).ok


def test_spanish_on_x_blocked_plain_message():
    r = check_draft(ES_CARTA, CARTA)
    assert "lang_mismatch" in codes(r)
    assert "This X draft looks Spanish; X posts are English-only." in [x["message"] for x in r.reasons]


def test_spanish_on_linkedin_blocked_econllm_door():
    r = check_draft("Los agentes culturales sintéticos pueden seguir el comportamiento no-WEIRD de los experimentos.", {**SCA, "outlet": "linkedin"})
    assert "lang_mismatch" in codes(r)


def test_carta_outlet_spanish_passes_and_english_blocked():
    card = {**CARTA, "outlet": "carta", "slugs": ["verification-local-context"]}
    assert check_draft(ES_CARTA, card).ok, check_draft(ES_CARTA, card).reasons
    assert "lang_mismatch" in codes(check_draft(GOOD_CARTA, {**card, "outlet": "oped"}))


@pytest.mark.parametrize("bait", ["DM me for details.", "Link in bio.", "Follow me for more.",
                                  "Subscribe to my newsletter.", "Check out my paper.", "Sign up now."])
def test_cta_english(bait):
    assert "cta_bait" in codes(check_draft(GOOD_CARTA + " " + bait, CARTA))


@pytest.mark.parametrize("bait", ["Seguime para más.", "Suscribite al boletín.", "Link en bio.", "Escribime por privado."])
def test_cta_spanish(bait):
    assert "cta_bait" in codes(check_draft(ES_CARTA + " " + bait, {**CARTA, "outlet": "carta"}))


def test_two_links_blocked():
    r = check_draft(GOOD_SCA + " https://example.com/x", {**SCA, "outlet": "linkedin"})
    assert "cta_bait" in codes(r)


def test_claim_missing():
    r = check_draft("Great thread, totally agree with everything said here today.", CARTA)
    assert "claim_missing" in codes(r)


def test_door_mix_civic_with_lab_branding():
    assert "door_mix" in codes(check_draft(GOOD_CARTA + " Our lab at EconLLM studies this.", CARTA))


def test_door_mix_econllm_as_civic_oped():
    assert "door_mix" in codes(check_draft(GOOD_SCA.replace("https://arxiv.org/abs/2501.06834", "") + " I wrote an op-ed on this.", SCA))


def test_x_length_url_counts_23():
    long_url = "https://arxiv.org/abs/2501.06834?" + "a" * 200
    assert x_length("hi " + long_url) == 3 + 23


def test_too_long_x_but_ok_linkedin():
    text = (GOOD_CARTA + " ") * 3
    assert "too_long" in codes(check_draft(text, CARTA))
    assert "too_long" not in codes(check_draft(text, {**CARTA, "outlet": "linkedin"}))


def test_invented_metric_blocked():
    assert "invented_metric" in codes(check_draft(GOOD_CARTA + " Verification cut misinfo by 40%.", CARTA))
    assert "invented_metric" in codes(check_draft(GOOD_CARTA + " It is 3x times faster.", CARTA))


def test_metric_allowed_when_in_claim():
    card = {**CARTA, "asset_claim": CARTA["asset_claim"] + " Local desks verified 40% more claims."}
    assert "invented_metric" not in codes(check_draft(GOOD_CARTA + " Local desks verified 40% more.", card))


def test_gate_never_edits_and_codes_stable():
    text = GOOD_CARTA + " DM me"
    r = check_draft(text, CARTA)
    assert not r.ok and text == GOOD_CARTA + " DM me"
    for x in r.reasons:
        assert x["code"] in CODES and x["message"]


def test_empty():
    assert codes(check_draft("  ", CARTA)) == {"empty_draft"}


# ── Adversarial Tester attacks (2026-10-09 17:48) ──────────────────────────────

@pytest.mark.parametrize("bait", ["\u216e\U0001d5ac me", "D M me", "D\u200bM me", "D.M. me", "f o l l o w me", "s\ufeffubscribe"])
def test_obfuscated_cta_blocked(bait):
    text = GOOD_CARTA + " " + bait
    r = check_draft(text, CARTA)
    assert "cta_bait" in codes(r)
    assert text == GOOD_CARTA + " " + bait  # draft untouched


@pytest.mark.parametrize("link", ["see evil.example/x", "see bit.ly/abc", "example.com"])
def test_bare_domains_are_links(link):
    assert "cta_bait" in codes(check_draft(GOOD_CARTA + " " + link, CARTA))
    assert "cta_bait" in codes(check_draft(GOOD_SCA + " " + link, SCA))  # two links


def test_eg_and_decimals_not_links():
    r = check_draft(GOOD_CARTA + " e.g. local desks, version 2.5 of the rules.", CARTA)
    assert "cta_bait" not in codes(r)


@pytest.mark.parametrize("url", ["https://arxiv.org/abs/2501.06834/../../evil", "https://arxiv.org/abs/2501.06834/extra",
                                 "https://arxiv.org.evil.example/abs/2501.06834", "https://arxlv.org/abs/2501.06834"])
def test_asset_link_must_match_exactly(url):
    r = check_draft(GOOD_SCA.replace("https://arxiv.org/abs/2501.06834", url), SCA)
    assert "cta_bait" in codes(r)


@pytest.mark.parametrize("url", ["https://arxiv.org/abs/2501.06834/", "http://ARXIV.org/abs/2501.06834?utm_source=x#f", "arxiv.org/abs/2501.06834."])
def test_asset_link_normalized_variants_pass(url):
    assert check_draft(GOOD_SCA.replace("https://arxiv.org/abs/2501.06834", url), SCA).ok


@pytest.mark.parametrize("door", [None, "", "econllm", "Perwell"])
def test_card_without_valid_door_refused(door):
    card = {k: v for k, v in CARTA.items() if k != "door"}
    if door is not None:
        card["door"] = door
    r = check_draft(GOOD_CARTA, card)
    assert not r.ok
    assert {"code": "door_missing", "message": "This card has no voice set; pick EconLLM or Augusto-civic."} in r.reasons


def wcodes(r):
    return {x["code"] for x in r.warnings}


def test_word_metrics_warn_not_block():
    r = check_draft(GOOD_SCA + " Forty percent better, doubling accuracy.", {**SCA, "outlet": "linkedin"})
    assert r.ok and "possible_metric" in wcodes(r)
    r2 = check_draft(ES_CARTA + " Mejora dos veces, cuarenta por ciento más.", {**CARTA, "outlet": "carta"})
    assert r2.ok and "possible_metric" in wcodes(r2)


def test_negated_claim_warns():
    r = check_draft("Synthetic cultural agents do NOT track non-WEIRD behavior in experiments.", SCA)
    assert r.ok and "claim_negated" in wcodes(r)


def test_short_spanish_on_x_warns_uncertain():
    r = check_draft("Verificación local ya.", CARTA)
    assert "lang_uncertain" in wcodes(r) or "lang_mismatch" in codes(r)
    assert "lang_uncertain" in wcodes(check_draft("Verificación local.", CARTA))


def test_clean_pass_has_no_warnings_and_to_dict_shape():
    d = check_draft(GOOD_CARTA, CARTA).to_dict()
    assert d == {"ok": True, "reasons": [], "warnings": [], "tags": {"has_profanity": False, "has_put_down": False}}


# ── Adversarial round 2 (2026-10-09 17:52) ─────────────────────────────────────

A = "https://arxiv.org/abs/2501.06834"


@pytest.mark.parametrize("url", [
    A + "?utm_source=x&next=https://evil.example",
    A + "?next=foo",
    A + "?utm_source=https://evil.example",
    A + "?utm_source=http%3A%2F%2Fevil.example",
    A + "?utm_source=%252F%252Fevil",
    A + "?utm_source=evil.example",
    A + "?utm_source=//evil",
    A + "#https://evil.example",
    A + "#see-evil.example",
])
def test_asset_link_query_smuggling_blocked(url):
    assert "cta_bait" in codes(check_draft(GOOD_SCA.replace(A, url), SCA))


@pytest.mark.parametrize("url", [A + "/", "https://ARXIV.org/abs/2501.06834", "https://www.arxiv.org/abs/2501.06834",
                                 A + "?utm_source=x", A + "?utm_source=x&utm_medium=social", A + ".", A + "#section-2"])
def test_asset_link_safe_variants_pass(url):
    r = check_draft(GOOD_SCA.replace(A, url), SCA)
    assert r.ok, r.reasons


@pytest.mark.parametrize("bait", ["Reply 'yes' and I'll send the preprint.", "Comment PDF to get the slides.",
                                  "Drop a 🔥 and I will DM the code.", "RT for the full dataset.",
                                  "Like this for a copy.", "R e p l y yes and I'll send it."])
def test_engagement_bait_english(bait):
    assert "cta_bait" in codes(check_draft(GOOD_CARTA + " " + bait, CARTA))


@pytest.mark.parametrize("bait", ["Respondé 'sí' y te envío el borrador.", "Comentá CARTA para recibir el texto.",
                                  "Dejá un comentario y te paso el link."])
def test_engagement_bait_spanish(bait):
    assert "cta_bait" in codes(check_draft(ES_CARTA + " " + bait, {**CARTA, "outlet": "carta"}))


@pytest.mark.parametrize("prose", ["In reply to your point, verification still matters.",
                                   "I like this framing for its focus on local context.",
                                   "Many people share the view that bans fail."])
def test_reply_in_prose_not_flagged(prose):
    assert "cta_bait" not in codes(check_draft(GOOD_CARTA + " " + prose, {**CARTA, "outlet": "linkedin"}))


@pytest.mark.parametrize("bait", ["Responde 'sí' y te envío el paper.", "Comenta PDF para recibir las diapositivas.",
                                  "Escribi CARTA y te lo mando.", "Deja un comentario y te lo paso.",
                                  "Comparte esto y te envío el borrador.", "Compartí y te lo envío.",
                                  "Dale like para recibir el texto."])
def test_engagement_bait_spanish_tu_forms(bait):
    assert "cta_bait" in codes(check_draft(ES_CARTA + " " + bait, {**CARTA, "outlet": "carta"}))


def test_responde_in_spanish_prose_not_flagged():
    prose = "La verificación local responde a una necesidad pública que la generación barata no cubre."
    assert "cta_bait" not in codes(check_draft(ES_CARTA + " " + prose, {**CARTA, "outlet": "carta"}))


def test_claim_restated_blocks_first_sentence_echo():
    """Designer P2 #7: first sentence must not near-verbatim restate the claim (ead2-style)."""
    claim = CARTA["asset_claim"]
    bad = f"{claim} Community Notes caught the watermark, which is the scarce bit."
    r = check_draft(bad, CARTA)
    assert "claim_restated" in codes(r), r.reasons
    assert any("Respond to the post" in x["message"] for x in r.reasons)


def test_claim_restated_allows_post_first_reply():
    good = ('Community notes caught an OpenAI SynthID watermark, and that catch is the scarce bit: '
            "generation is cheap, so verification and local context become the scarce public goods. "
            "Not published yet: an argument, not evidence.")
    card = {**CARTA, "asset_caveat": "Not published yet: an argument, not evidence.",
            "slugs": ["cheap-gen-scarce-verify"],
            "asset_claim": "Generation and amplification are cheap; verification and locally named context are scarce public goods."}
    r = check_draft(good, card)
    assert "claim_restated" not in codes(r), r.reasons
    assert r.ok or "claim_missing" not in codes(r), r.reasons


def test_ead2_local_template_style_restatement_blocked():
    """Live card_ead2fc06ec82 pattern: Adepa claim + caveat as the whole draft."""
    draft = ("Generation/amplification is cheap; verification + local context are scarce — "
             "coexist with AI, don’t ban. Not published yet: an argument, not evidence.")
    card = {**CARTA, "slugs": ["cheap-gen-scarce-verify"],
            "asset_claim": "Generation and amplification are cheap; verification and locally named context are scarce public goods.",
            "asset_caveat": "Not published yet: an argument, not evidence."}
    assert "claim_restated" in codes(check_draft(draft, card))
