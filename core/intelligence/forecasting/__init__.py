"""
core/intelligence/forecasting
=============================
Anticipation as a first-class intelligence capability.

Reasoning explains the present; forecasting commits to the future — a
probability, a horizon, a lead time, and a recommended action, then grades
itself when the future arrives so it improves with operational experience.

Borrowing from weather (probabilistic + cone of uncertainty), aviation/ATC
(lead time, separation, go-around), finance (calibration, expected loss),
power grids (load + N-1 cascade), autonomous vehicles (time-to-collision),
industrial automation (Weibull RUL, software-aging rejuvenation), military
(course-of-action, indications & warning) and medicine (early-warning score,
prognosis).

  from core.intelligence.forecasting import get_prediction_engine, wire_prediction
  wire_prediction()                                   # at startup
  eng = get_prediction_engine()
  board = eng.forecast({"device": "192.168.96.133", "intent": "...", "protocol": "ospf"})
  ew = eng.early_warning({"device": "192.168.96.133"})
  eng.resolve_outcomes()                              # continuous improvement loop
"""
from core.intelligence.forecasting.engine import (
    PredictionEngine, get_prediction_engine, wire_prediction,
)
from core.intelligence.forecasting.base import (
    Forecast, Forecaster, ForecasterSpec, ForecastType, Driver, ForecastRegistry,
)

__all__ = [
    "PredictionEngine", "get_prediction_engine", "wire_prediction",
    "Forecast", "Forecaster", "ForecasterSpec", "ForecastType", "Driver",
    "ForecastRegistry",
]
