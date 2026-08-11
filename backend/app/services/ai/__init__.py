"""AI intelligence (Module H).

Layered so the provider is the only part that talks to a network:

    prompts.py    prompt construction and the untrusted-input boundary
    providers.py  OpenAI and a deterministic offline analyser
    analysis.py   orchestration, caching, budget, and the anonymity gate
"""

from app.services.ai.analysis import (
    analyse_cycle,
    monthly_tokens_used,
    sentiment_breakdown,
    summarise_target,
)
from app.services.ai.providers import build_provider

__all__ = [
    "analyse_cycle",
    "build_provider",
    "monthly_tokens_used",
    "sentiment_breakdown",
    "summarise_target",
]
