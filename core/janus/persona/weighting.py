from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ..memory.models import Persona, utcnow
from ..memory.store import JanusStore

FEATURE_DIMENSIONS: dict[str, str] = {
    "rsi_14": "contrarian",
    "macd_hist": "contrarian",
    "return_21d": "contrarian",
    "atr_14_pct": "drawdown",
    "bb_width_20": "drawdown",
    "relative_strength_63": "quality",
    "breadth": "macro",
    "valuation": "valuation",
    "quality": "quality",
    "macro": "macro",
    "liquidity": "liquidity",
}


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    text: str
    categories: tuple[str, ...]
    source: str = ""


class PersonaPolicy:
    """Turn a taste profile into feature weights and an evidence ranking."""

    def __init__(self, profile: dict[str, float]) -> None:
        self.profile = profile

    def feature_weights(self) -> dict[str, float]:
        return {
            feature: 0.5 + float(self.profile.get(dimension, 0.5))
            for feature, dimension in FEATURE_DIMENSIONS.items()
        }

    def score(self, item: EvidenceItem) -> float:
        if not item.categories:
            return 1.0
        weights = self.feature_weights()
        return sum(weights.get(category, 0.5) for category in item.categories) / len(
            item.categories
        )

    def rank(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        return sorted(items, key=lambda item: (-self.score(item), item.id))


def build_persona(
    *,
    profile: dict[str, float],
    name: str,
    persona_id: str | None = None,
) -> Persona:
    policy = PersonaPolicy(profile)
    return Persona(
        id=persona_id or uuid4().hex,
        name=name,
        profile=dict(profile),
        weights=policy.feature_weights(),
        rules={"version": "v1", "ranking": "weighted-category-mean"},
        created_at=utcnow(),
    )


class PersonaService:
    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def save(self, persona: Persona) -> None:
        self.store.insert_persona(persona)

    def get(self, persona_id: str) -> Persona | None:
        return self.store.get_persona(persona_id)

    def compare(
        self,
        items: list[EvidenceItem],
        personas: list[Persona],
    ) -> dict[str, list[str]]:
        return {
            persona.name: [item.id for item in PersonaPolicy(persona.profile).rank(items)]
            for persona in personas
        }

    def weights(self, persona: Persona) -> dict[str, float]:
        return PersonaPolicy(persona.profile).feature_weights()


def persona_from_dict(payload: dict[str, Any]) -> Persona:
    return Persona.model_validate(payload)
