"""Frozen language gate (src/lang_gate.py): constants pinned; X posts are capped unless clearly English."""
import json
import subprocess
import sys

import pytest

from src import lang_gate as lg

EN = ("Ask GPT a values question and its answers drift toward what WEIRD respondents say; responses from "
      "non-Western surveys get flattened toward that center. Simulated respondents aren't culturally neutral.")
ES = ("Los agentes culturales sintéticos de LLM pueden rastrear cualitativamente el comportamiento no-WEIRD... "
      "igual que mi gato rastrea la heladera a las 3am jajaja 😹")
ES_PLUS_EN = ("This is a point that matters for all of us in the field. "
              "Los modelos no pueden reemplazar a los datos de campo y eso es lo que importa.")
PT = "Os agentes sintéticos não podem substituir os dados de campo, mas são úteis para pilotar desenhos."
FR = "Les agents synthétiques ne peuvent pas remplacer les données de terrain, mais ils sont utiles pour les pilotes."
IT = "Gli agenti sintetici non possono sostituire i dati sul campo, ma sono utili per i pilota e per la ricerca."
JA = "合成エージェントは現地調査の代わりにはなりません。これは重要です。 But this is the point that matters for us."
RU = "Синтетические агенты не могут заменить полевые данные, это важно. But this is the point that matters for us."


def test_constants_frozen():
    assert (lg.NON_LATIN_MAX, lg.MIN_ELIGIBLE, lg.MIN_SIGNAL) == (0.20, 4, 2)
    assert set(lg.STOP) == {"en", "es", "pt", "fr", "it", "de"}


def test_clean_english_passes():
    r = lg.classify(EN)
    assert r["clearly_english"] and r["lang"] == "en" and r["reason"] == "clearly_english"


@pytest.mark.parametrize("t,lang", [(ES, "es"), (PT, "pt"), (FR, "fr"), (IT, "it")])
def test_other_latin_languages_capped(t, lang):
    r = lg.classify(t)
    assert not r["clearly_english"] and r["lang"] == lang and r["reason"] == "non_english_sentence"


def test_spanish_plus_one_english_sentence_capped_mixed():
    r = lg.classify(ES_PLUS_EN)
    assert not r["clearly_english"] and r["lang"] == "mixed" and r["detected"] == "es"


@pytest.mark.parametrize("t", [JA, RU])
def test_non_latin_body_with_english_clause_capped(t):
    r = lg.classify(t)
    assert not r["clearly_english"] and r["reason"] == "non_latin_script" and r["non_latin_share"] > 0.20


def test_short_jargon_sentences_neutral_not_triggers():
    r = lg.classify("LLM ABM RL. " + EN + " Fig 2, n=40.")
    assert r["clearly_english"]


def test_very_short_english_post_behaviour():
    # 17:05 PT fix: English signal counted over the whole post. Two+ English-only stopwords pass even if every
    # sentence is short; fewer (no English signal at all) are still capped.
    assert lg.classify("This. So much this.")["clearly_english"]
    for t in ("Great paper!", "LLM agents ftw 🔥 https://x.com/fixture_user_54/status/1 #ai"):
        r = lg.classify(t)
        assert not r["clearly_english"] and r["reason"] == "no_english_signal" and r["lang"] == "unknown"


def test_urls_handles_hashtags_ignored():
    assert lg.classify(EN + " https://elpais.com/la-de-los-que-por @fixture_user_29 #para_los_que").get("clearly_english")


def test_cli_jsonl(tmp_path):
    f = tmp_path / "x.jsonl"
    f.write_text("\n".join(json.dumps({"id": i, "text": t}) for i, t in enumerate([EN, ES])))
    out = subprocess.run([sys.executable, "-m", "src.lang_gate", str(f)], capture_output=True, text=True, check=True)
    rows = [json.loads(l) for l in out.stdout.splitlines()]
    assert [r["clearly_english"] for r in rows] == [True, False] and rows[1]["lang"] == "es"


# ── 17:05 PT fixes: whole-post English signal + NFKC (DA reports/eval/lang_gate_check.md) ──
PEW = ('A made-up survey lab tested "sample twins", using AI to stand in for survey respondents.\n\n'
       "The twins missed the real poll results by 9.1 percentage points on average.\n\n"
       "Models can echo people. They can't stand in for asking them.")   # made-up post (no real text)
REPRO = ("Reliability is not validity: a made-up paper on model measurement of everyday workplace chat\n\n"
         "Fixture Author One, Fixture Author Two Example\n"
         "https://example.invalid/a1 [𝚌𝚜.𝙰𝙸 𝚌𝚜.𝙲𝙻 𝚌𝚜.𝙲𝚈 𝚚-𝚏𝚒𝚗.𝚁𝙼] https://example.invalid/a2")


def _bold(s):   # MATHEMATICAL BOLD letters
    out = []
    for ch in s:
        if "A" <= ch <= "Z":
            out.append(chr(0x1D400 + ord(ch) - 65))
        elif "a" <= ch <= "z":
            out.append(chr(0x1D41A + ord(ch) - 97))
        else:
            out.append(ch)
    return "".join(out)


def _italic(s):  # MATHEMATICAL ITALIC letters (h is a hole in the block → plain h)
    return "".join(chr(0x1D44E + ord(c) - 97) if "a" <= c <= "z" and c != "h" else c for c in s)


@pytest.mark.parametrize("t", [PEW, REPRO])
def test_da_examples_clearly_english(t):
    r = lg.classify(t)
    assert r["clearly_english"] and r["reason"] == "clearly_english", r


def test_all_short_sentence_english_passes():
    r = lg.classify("This is it. We did the work. It is not easy. You can see why.")
    assert r["clearly_english"] and r["en_share"] > 0.5


def test_short_split_spanish_english_hashtag_still_caps():
    r = lg.classify("Los modelos no sirven. #AI rocks. La data es clave. Es lo que hay.")
    assert not r["clearly_english"] and r["reason"] in ("non_english_words", "non_english_sentence")
    assert r["detected"] == "es"
    r2 = lg.classify("Ojo. #LLM rocks. La data. Es clave. Lo que hay.")      # every sentence short
    assert not r2["clearly_english"] and r2["reason"] == "non_english_words" and r2["detected"] == "es"


def test_bold_and_italic_unicode_english_is_english():
    for t in (_bold(PEW), _italic("this is what we found: the model is not neutral and it can not replace the survey.")):
        r = lg.classify(t)
        assert r["clearly_english"] and r["reason"] != "non_latin_script", r


def test_bold_unicode_spanish_capped_as_spanish():
    r = lg.classify(_bold("Los modelos de lenguaje no pueden reemplazar a las encuestas de campo en la provincia."))
    assert not r["clearly_english"] and r["lang"] == "es"


def test_constants_unchanged_after_fix():
    assert (lg.NON_LATIN_MAX, lg.MIN_ELIGIBLE, lg.MIN_SIGNAL) == (0.20, 4, 2)
