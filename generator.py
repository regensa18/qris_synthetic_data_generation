"""
generator.py

Core synthetic QRIS merchant transaction data generator.

This module holds the real, importable logic — it's the source of truth.
Exploration/plotting/parameter-tuning happens in exploration.ipynb, which
imports from here rather than duplicating logic.

Current state: steady archetype, with location_type as a weekly-seasonality
modifier (per design doc) and ground-truth labels attached to the output.
"""

import numpy as np
import pandas as pd


def get_weekly_multiplier(dates, location_type: str = "residential") -> np.ndarray:
    """
    Returns a per-day multiplier array based on location_type,
    per the design doc's weekly seasonality modifiers.

    - residential: mild weekend bump (default assumption)
    - office_district: weekday-high, sharp weekend drop
    - attraction: weekend-high, weekday-low
    - market: roughly flat by day-of-week (baseline, no strong weekly signal)
    """
    is_weekend = dates.weekday >= 5

    if location_type == "residential":
        return np.where(is_weekend, 1.15, 1.0)
    elif location_type == "office_district":
        return np.where(is_weekend, 0.4, 1.0)
    elif location_type == "attraction":
        return np.where(is_weekend, 1.7, 0.6)
    elif location_type == "market":
        return np.ones(len(dates))
    else:
        raise ValueError(f"Unknown location_type: {location_type}")


def generate_steady_merchant(
    days: int = 180,
    base_revenue: float = 500_000,
    noise_sigma: float = 0.08,
    location_type: str = "residential",
    start_date: str = "2025-01-01",
    seed: int | None = None,
) -> dict:
    """
    Generate a daily revenue series for a 'steady' archetype merchant,
    with a location_type modifier controlling weekly seasonality shape.

    revenue(t) = base_revenue * weekly_multiplier(t, location_type) * lognormal_noise(t)

    Returns a dict bundling the data with its ground-truth labels:
        {
            "data": pd.DataFrame with columns [date, revenue],
            "archetype": "steady",
            "expected_eligible": True,
            "params": {...},
        }
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, periods=days, freq="D")

    weekly_multiplier = get_weekly_multiplier(dates, location_type)
    noise = rng.lognormal(mean=0.0, sigma=noise_sigma, size=days)
    revenue = base_revenue * weekly_multiplier * noise

    df = pd.DataFrame({"date": dates, "revenue": revenue})

    return {
        "data": df,
        "archetype": "steady",
        "expected_eligible": True,
        "params": {
            "base_revenue": base_revenue,
            "noise_sigma": noise_sigma,
            "location_type": location_type,
        },
    }


if __name__ == "__main__":
    # Quick smoke test when running this file directly:
    #   python generator.py
    result = generate_steady_merchant(seed=42)
    print(result["data"].head())
    print(f"\nArchetype: {result['archetype']}, expected_eligible: {result['expected_eligible']}")
    print(f"Params: {result['params']}")
