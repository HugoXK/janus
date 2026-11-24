from __future__ import annotations

from janus.memory.store import JanusStore
from janus.persona.profile import DIMENSIONS
from janus.persona.weighting import (
    EvidenceItem,
    PersonaPolicy,
    PersonaService,
    build_persona,
)


def _profile(**overrides: float) -> dict[str, float]:
    profile = {dimension: 0.5 for dimension in DIMENSIONS}
    profile.update(overrides)
    return profile


def test_persona_ranking_changes_with_taste() -> None:
    buffett = _profile(quality=0.9, valuation=0.3, macro=0.2, contrarian=0.25)
    soros = _profile(macro=0.9, contrarian=0.6, quality=0.4)
    quality = EvidenceItem(id="q", text="margins", categories=("quality",))
    macro = EvidenceItem(id="m", text="rates", categories=("macro",))

    assert PersonaPolicy(buffett).rank([macro, quality])[0].id == "q"
    assert PersonaPolicy(soros).rank([macro, quality])[0].id == "m"


def test_persona_is_stored_with_weights() -> None:
    store = JanusStore(":memory:")
    persona = build_persona(profile=_profile(quality=0.9), name="Buffett")
    service = PersonaService(store)
    service.save(persona)

    loaded = service.get(persona.id)
    assert loaded is not None
    assert loaded.name == "Buffett"
    assert service.weights(loaded)["quality"] > service.weights(loaded)["macro"]
    assert len(store.list_personas()) == 1


def test_persona_comparison() -> None:
    buffett = build_persona(profile=_profile(quality=0.9, macro=0.2), name="Buffett")
    soros = build_persona(profile=_profile(quality=0.2, macro=0.9), name="Soros")
    items = [
        EvidenceItem(id="q", text="", categories=("quality",)),
        EvidenceItem(id="m", text="", categories=("macro",)),
    ]

    ranking = PersonaService(JanusStore(":memory:")).compare(items, [buffett, soros])

    assert ranking["Buffett"][0] == "q"
    assert ranking["Soros"][0] == "m"
