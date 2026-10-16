"""Generate SPA test fixtures from the real Python truth layer (temp data dir; never the live DB)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]
SCA, ADEPA = "asset_sca_nonweird", "asset_adepa_lagaceta_carta"
X_WEIRD = dict(url="https://x.com/fixture_user_54/status/1", outlet="x", reply_count=6, quote_count=1, like_count=900,
               author="fixture_user_23",
               snippet="Are LLM synthetic participants just WEIRD? non-WEIRD cultural agent results")
CIVIC = dict(url="https://www.lagaceta.com.ar/nota/1", outlet="x", reply_count=3,
             author="fixture_user_22",
             snippet="Desinformación en Tucumán: Community Notes y verificación con contexto local")
PROMO = dict(url="https://x.com/fixture_user_63/status/2", outlet="x", snippet="Buy my course now! link in bio, DM me")
MULTI = dict(url="https://x.com/fixture_user_55/status/3", outlet="x",
             snippet="construct validity of LLM survey scores and WEIRD cultural agents, non-WEIRD")


def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        c = TestClient(create_app(d))
        out: dict = {"inventory": c.get("/inventory").json()}
        sca = c.post(f"/recommend?asset_id={SCA}", json=X_WEIRD).json()
        civ = c.post(f"/recommend?asset_id={ADEPA}", json=CIVIC).json()
        out["rec_sca"], out["rec_civic"] = sca, civ
        out["rec_kill"] = c.post(f"/recommend?asset_id={SCA}", json=PROMO).json()
        out["rec_general"] = c.post("/recommend", json=MULTI).json()
        out["handoff_sca"] = c.post("/handoff", json={"card_id": sca["card"]["card_id"]}).json()
        # Adepa's topics are all off x-brief's list -> no_lens; civic handoff fixture uses a mixed op-ed asset.
        c.post("/inventory", json={"asset_id": "asset_civic_mix", "title": "Carta mix", "door": "Augusto-civic",
                                   "slugs": ["verification-local-context", "ai-society-governance"], "surface": "carta",
                                   "oped_status": "pending", "evidence_grade": "A", "tone_hint": "civic Spanish op-ed"})
        mix = c.post("/recommend?asset_id=asset_civic_mix",
                     json={**CIVIC, "url": "https://www.lagaceta.com.ar/nota/2", "snippet": CIVIC["snippet"] + " - ai governance"}).json()
        out["rec_civic_mix"] = mix
        out["handoff_civic"] = c.post("/handoff", json={"card_id": mix["card"]["card_id"]}).json()
        out["pending"] = c.get("/handoff", params={"status": "pending"}).json()
        out["queue"] = c.get("/queue").json()
    dst = ROOT / "web" / "src" / "test" / "fixtures.json"
    dst.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print("wrote", dst, {k: (v.get("status") if isinstance(v, dict) else len(v)) for k, v in out.items()})


if __name__ == "__main__":
    main()
