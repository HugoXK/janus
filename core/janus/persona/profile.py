from __future__ import annotations

import math
from typing import Optional

DIMENSIONS = [
    "horizon",
    "drawdown",
    "concentration",
    "valuation",
    "macro",
    "quality",
    "contrarian",
    "liquidity",
    "discipline",
]

# Each question maps an option index to a 0..1 value on one dimension.
# Low and high are intentionally directional:
#   valuation: 0 = deep value, 1 = momentum
#   macro:     0 = bottom-up, 1 = macro-driven
#   quality:   0 = deep value, 1 = quality
#   contrarian:0 = contrarian, 1 = trend-following
#   liquidity: 0 = large/liquid, 1 = small/illiquid
QUESTIONS: list[dict] = [
    {
        "id": "horizon",
        "prompt": "你的投资时间尺度更接近？",
        "dimension": "horizon",
        "options": [("几天", 0.1), ("几周", 0.3), ("几个月", 0.5), ("几年", 0.9)],
    },
    {
        "id": "drawdown",
        "prompt": "你能忍受的最大回撤？",
        "dimension": "drawdown",
        "options": [("5%", 0.1), ("10%", 0.3), ("20%", 0.6), ("40% 以上", 0.9)],
    },
    {
        "id": "concentration",
        "prompt": "你的持仓集中度？",
        "dimension": "concentration",
        "options": [("指数化", 0.1), ("分散", 0.3), ("集中", 0.7), ("极度集中", 0.9)],
    },
    {
        "id": "valuation",
        "prompt": "你更看重估值还是动量？",
        "dimension": "valuation",
        "options": [("只看估值", 0.1), ("偏估值", 0.3), ("平衡", 0.5), ("偏动量", 0.7), ("只看动量", 0.9)],
    },
    {
        "id": "macro",
        "prompt": "你更偏宏观驱动还是公司驱动？",
        "dimension": "macro",
        "options": [("只看公司", 0.1), ("偏公司", 0.3), ("平衡", 0.5), ("偏宏观", 0.7), ("只看宏观", 0.9)],
    },
    {
        "id": "quality",
        "prompt": "你更偏深度价值还是高质量？",
        "dimension": "quality",
        "options": [("深度价值", 0.1), ("偏价值", 0.3), ("平衡", 0.5), ("偏质量", 0.7), ("只看质量", 0.9)],
    },
    {
        "id": "contrarian",
        "prompt": "你更偏逆向还是趋势？",
        "dimension": "contrarian",
        "options": [("逆向", 0.1), ("偏逆向", 0.3), ("平衡", 0.5), ("偏趋势", 0.7), ("趋势", 0.9)],
    },
    {
        "id": "liquidity",
        "prompt": "你的规模/流动性偏好？",
        "dimension": "liquidity",
        "options": [("只做大盘", 0.1), ("偏大盘", 0.3), ("平衡", 0.5), ("偏小盘", 0.7), ("只做小盘", 0.9)],
    },
    {
        "id": "risk_budget",
        "prompt": "单笔交易愿意承担的风险？",
        "dimension": "drawdown",
        "options": [("0.5%", 0.1), ("1%", 0.3), ("2%", 0.5), ("5%", 0.8), ("10%", 1.0)],
    },
    {
        "id": "discipline",
        "prompt": "什么最可能让你认错？",
        "dimension": "discipline",
        "options": [("价格止损", 0.2), ("基本面恶化", 0.4), ("逻辑被证伪", 0.7), ("很少认错", 0.9)],
    },
]

# Master vectors are priors, not stereotypes. Values are 0..1 on each dimension.
MASTERS: dict[str, dict[str, float]] = {
    "Buffett": {
        "horizon": 0.9,
        "drawdown": 0.7,
        "concentration": 0.8,
        "valuation": 0.3,
        "macro": 0.2,
        "quality": 0.9,
        "contrarian": 0.25,
        "liquidity": 0.2,
        "discipline": 0.7,
    },
    "Graham": {
        "horizon": 0.7,
        "drawdown": 0.6,
        "concentration": 0.5,
        "valuation": 0.1,
        "macro": 0.2,
        "quality": 0.5,
        "contrarian": 0.3,
        "liquidity": 0.4,
        "discipline": 0.8,
    },
    "Lynch": {
        "horizon": 0.6,
        "drawdown": 0.5,
        "concentration": 0.5,
        "valuation": 0.5,
        "macro": 0.2,
        "quality": 0.6,
        "contrarian": 0.4,
        "liquidity": 0.6,
        "discipline": 0.5,
    },
    "Dalio": {
        "horizon": 0.7,
        "drawdown": 0.4,
        "concentration": 0.4,
        "valuation": 0.4,
        "macro": 0.95,
        "quality": 0.6,
        "contrarian": 0.4,
        "liquidity": 0.3,
        "discipline": 0.8,
    },
    "Soros": {
        "horizon": 0.3,
        "drawdown": 0.8,
        "concentration": 0.8,
        "valuation": 0.4,
        "macro": 0.9,
        "quality": 0.4,
        "contrarian": 0.6,
        "liquidity": 0.2,
        "discipline": 0.4,
    },
    "Simons": {
        "horizon": 0.1,
        "drawdown": 0.4,
        "concentration": 0.3,
        "valuation": 0.5,
        "macro": 0.1,
        "quality": 0.3,
        "contrarian": 0.5,
        "liquidity": 0.2,
        "discipline": 0.9,
    },
    "Templeton": {
        "horizon": 0.8,
        "drawdown": 0.8,
        "concentration": 0.6,
        "valuation": 0.1,
        "macro": 0.5,
        "quality": 0.4,
        "contrarian": 0.1,
        "liquidity": 0.5,
        "discipline": 0.7,
    },
    "O'Neil": {
        "horizon": 0.3,
        "drawdown": 0.2,
        "concentration": 0.5,
        "valuation": 0.6,
        "macro": 0.4,
        "quality": 0.7,
        "contrarian": 0.8,
        "liquidity": 0.5,
        "discipline": 0.9,
    },
}


def profile_from_answers(answers: dict[str, int]) -> dict[str, float]:
    """Convert question id -> option index into a normalized profile vector."""

    buckets: dict[str, list[float]] = {dimension: [] for dimension in DIMENSIONS}
    for question in QUESTIONS:
        if question["id"] not in answers:
            continue
        index = answers[question["id"]]
        options = question["options"]
        if not 0 <= index < len(options):
            continue
        buckets[question["dimension"]].append(float(options[index][1]))

    profile: dict[str, float] = {}
    for dimension in DIMENSIONS:
        values = buckets[dimension]
        profile[dimension] = sum(values) / len(values) if values else 0.5
    return profile


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(a.get(key, 0.0) * b.get(key, 0.0) for key in DIMENSIONS)
    norm_a = math.sqrt(sum(a.get(key, 0.0) ** 2 for key in DIMENSIONS))
    norm_b = math.sqrt(sum(b.get(key, 0.0) ** 2 for key in DIMENSIONS))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def match_master(
    profile: dict[str, float], masters: Optional[dict[str, dict[str, float]]] = None
) -> tuple[str, float]:
    """Return the closest master and its cosine similarity."""

    candidates = masters or MASTERS
    scored = [(_cosine(profile, vector), name) for name, vector in candidates.items()]
    score, name = max(scored)
    return name, score
