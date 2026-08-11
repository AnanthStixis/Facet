"""Predictive analytics and recommendations (Module H.2).

    sufficiency.py       the gate every model asks before reporting anything
    models.py            win probability, score trend, disengagement signal
    recommendations.py   deterministic rules that compute every number
"""

from app.services.analytics.models import (
    disengagement_signals,
    fit_win_probability,
    score_trend,
    score_win_probability,
)
from app.services.analytics.recommendations import build, generate

__all__ = [
    "build",
    "disengagement_signals",
    "fit_win_probability",
    "generate",
    "score_trend",
    "score_win_probability",
]
