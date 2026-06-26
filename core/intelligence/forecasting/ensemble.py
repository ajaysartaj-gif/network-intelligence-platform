"""
core/intelligence/forecasting/ensemble.py
==========================================
The portable forecasting mathematics — pure Python, no heavy deps.

These are the field-agnostic techniques the forecasters reuse:

  • pool_logodds   — combine many weak, independent signals into one probability
                     the way ensemble weather models pool members: average in
                     log-odds space so confident agreement compounds and lone
                     weak signals don't dominate.
  • ewma / trend   — exponential smoothing + least-squares slope, the backbone of
                     financial and power-grid load forecasting.
  • project        — extrapolate a trend to a horizon with a widening cone of
                     uncertainty (weather), and solve time-to-threshold (the
                     autonomous-vehicle "time to collision" / power-grid
                     time-to-peak).
  • weibull_hazard — bathtub-curve failure hazard for predictive maintenance
                     (industrial reliability / remaining-useful-life).
  • logistic       — squashing for score→probability mapping.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def logit(p: float) -> float:
    p = clamp(p, 1e-6, 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def logistic(score: float, midpoint: float = 0.5, steepness: float = 6.0) -> float:
    """Map an unbounded/[0,1] score to a probability with a tunable knee."""
    return sigmoid(steepness * (score - midpoint))


def pool_logodds(signals: Sequence[Tuple[float, float]], prior: float = 0.1) -> float:
    """
    Pool (probability, weight) pairs in log-odds space around a base rate prior.
    Ensemble weather pooling: each member nudges the prior; agreement compounds.
    Returns a probability in [0,1].
    """
    acc = logit(prior)
    wsum = 0.0
    for p, w in signals:
        if w <= 0:
            continue
        acc += w * (logit(clamp(p)) - logit(prior))
        wsum += w
    return clamp(sigmoid(acc))


def ewma(series: Sequence[float], alpha: float = 0.4) -> Optional[float]:
    if not series:
        return None
    s = float(series[0])
    for x in series[1:]:
        s = alpha * float(x) + (1 - alpha) * s
    return s


def linreg(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, float, float]:
    """Least-squares slope, intercept, and r² for ys over xs."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    r2 = (sxy * sxy) / (sxx * syy) if sxx and syy else 0.0
    return slope, intercept, r2


def stdev(series: Sequence[float]) -> float:
    n = len(series)
    if n < 2:
        return 0.0
    m = sum(series) / n
    return math.sqrt(sum((x - m) ** 2 for x in series) / (n - 1))


def project(times: Sequence[float], values: Sequence[float], horizon_s: float,
            threshold: Optional[float] = None) -> dict:
    """
    Project a time series to now+horizon with a widening uncertainty cone, and
    (if a threshold is given) estimate seconds until the trend crosses it.

    times are epoch seconds; values are the metric. Returns projected value,
    a ±band (cone) that grows with horizon and historical volatility, the
    fitted slope per second, r² (trend trustworthiness), and time_to_threshold.
    """
    if not times or not values or len(times) != len(values):
        return {"projection": None, "slope_per_s": 0.0, "r2": 0.0,
                "band": 0.0, "time_to_threshold_s": None}
    t0 = times[0]
    xs = [t - t0 for t in times]
    slope, intercept, r2 = linreg(xs, values)
    now = times[-1] - t0
    proj = intercept + slope * (now + horizon_s)
    vol = stdev(values)
    # cone widens with horizon, volatility, and trend uncertainty (1-r²).
    band = vol * (1 + horizon_s / max(1.0, (times[-1] - t0 + 1))) * (1.4 - 0.4 * r2)
    ttt = None
    if threshold is not None and slope > 1e-12:
        cur = intercept + slope * now
        if cur < threshold:
            ttt = (threshold - cur) / slope          # seconds to cross
        else:
            ttt = 0.0
    return {"projection": proj, "slope_per_s": slope, "r2": round(r2, 3),
            "band": band, "time_to_threshold_s": ttt}


def weibull_hazard(age_s: float, eta_s: float, beta: float = 1.6) -> float:
    """
    Weibull hazard rate at a given age (industrial predictive maintenance).
    beta<1 infant mortality, beta=1 random, beta>1 wear-out — the bathtub curve.
    eta is the characteristic life. Returns an instantaneous hazard, normalised
    to a [0,1] failure-likelihood proxy over a unit horizon.
    """
    if eta_s <= 0 or age_s < 0:
        return 0.0
    h = (beta / eta_s) * (age_s / eta_s) ** (beta - 1)
    # convert hazard·(characteristic life fraction) to a bounded probability.
    return clamp(1 - math.exp(-h * (eta_s * 0.05)))


def time_to_event(hazard_per_s: float) -> Optional[float]:
    """Expected seconds to an event given a constant hazard (1/λ)."""
    return (1.0 / hazard_per_s) if hazard_per_s > 0 else None
