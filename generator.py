import numpy as np
import pandas as pd


ARCHETYPE_CONFIGS = {
    "steady":    dict(trend_slope=0.0,     noise_sigma=0.08, archetype_label="steady",    expected_eligible=True),
    "growing":   dict(trend_slope=0.0025,  noise_sigma=0.10, archetype_label="growing",   expected_eligible=True),
    "declining": dict(trend_slope=-0.0025, noise_sigma=0.10, archetype_label="declining", expected_eligible=False),
    "volatile":  dict(trend_slope=0.0,     noise_sigma=0.45, archetype_label="volatile",  expected_eligible="ambiguous — genuine test case for rule engine judgment"),
    "seasonal": dict(
        trend_slope=0.0, noise_sigma=0.10,
        seasonal_peak_date="2025-03-31",  # example Lebaran date, adjust per year generated
        seasonal_amplitude=0.5,
        seasonal_width_days=10,
        archetype_label="seasonal", expected_eligible=True,
    )
}

def get_weekly_multiplier(dates, location_type="residential", holiday_calendar=None) -> np.ndarray:
    """
    Returns a per-day multiplier array based on location_type,
    with holiday_calendar treated as "weekend-equivalent" days.

    holiday_calendar: optional set/list of date strings or pd.Timestamps
        representing national holidays / long-weekend days (cuti bersama).
    """
    is_weekend = dates.weekday >= 5

    if holiday_calendar is not None:
        holiday_set = pd.to_datetime(list(holiday_calendar))
        is_holiday = dates.isin(holiday_set)
    else:
        is_holiday = np.zeros(len(dates), dtype=bool)

    # a day counts as "elevated" if it's a weekend OR a holiday
    is_elevated = is_weekend | is_holiday

    if location_type == "residential":
        return np.where(is_elevated, 1.15, 1.0)
    elif location_type == "office_district":
        return np.where(is_elevated, 0.4, 1.0)
    elif location_type == "attraction":
        return np.where(is_elevated, 1.7, 0.6)
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
    holidays: list[str] | None = None,
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

    weekly_multiplier = get_weekly_multiplier(dates, location_type, holidays)
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


def generate_event_based_merchant(
    days: int = 180,
    baseline_revenue: float = 20_000,   # near-zero, not literally zero — occasional stray transaction
    event_revenue: float = 1_500_000,   # revenue level during an active event
    event_noise_sigma: float = 0.15,
    n_events: int = 4,                  # how many bazaar events across the window
    event_duration_range: tuple = (2, 5),  # days per event, e.g. a 2-5 day bazaar
    start_date: str = "2025-01-01",
    seed: int | None = None,
) -> dict:
    """
    Generate a daily revenue series for an 'event_based' (bazaar) archetype merchant.

    Unlike continuous archetypes, this doesn't use trend+seasonality+noise.
    Instead: baseline near-zero every day, punctuated by randomly-placed
    event windows where revenue jumps to event_revenue level.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, periods=days, freq="D")

    # start with near-zero baseline for every day
    revenue = rng.lognormal(mean=np.log(baseline_revenue), sigma=0.3, size=days)

    # randomly place n_events non-overlapping event windows
    event_windows = []
    attempts = 0
    while len(event_windows) < n_events and attempts < 200:
        attempts += 1
        duration = rng.integers(event_duration_range[0], event_duration_range[1] + 1)
        start_idx = rng.integers(0, days - duration)
        end_idx = start_idx + duration

        # skip if it overlaps an existing event
        overlaps = any(start_idx < e[1] and end_idx > e[0] for e in event_windows)
        if not overlaps:
            event_windows.append((start_idx, end_idx))

    # apply event revenue inside each window
    for start_idx, end_idx in event_windows:
        window_len = end_idx - start_idx
        revenue[start_idx:end_idx] = rng.lognormal(
            mean=np.log(event_revenue), sigma=event_noise_sigma, size=window_len
        )

    df = pd.DataFrame({"date": dates, "revenue": revenue})

    return {
        "data": df,
        "archetype": "event_based",
        "expected_eligible": "ambiguous — requires event-aware scoring",
        "params": {
            "baseline_revenue": baseline_revenue,
            "event_revenue": event_revenue,
            "n_events": n_events,
            "event_windows": event_windows,  # keep the actual dates used, useful for debugging
        },
    }

def get_annual_multiplier(dates, seasonal_peak_date=None, seasonal_amplitude=0.0, seasonal_width_days=10):
    """
    Returns a per-day multiplier representing an annual seasonal bump
    (e.g. Ramadan/Lebaran spike), as a smooth Gaussian curve centered on
    seasonal_peak_date rather than a hard on/off window — real seasonal
    demand ramps up before and tapers down after, not a step function.

    seasonal_peak_date: the date of peak demand (e.g. Lebaran/Idul Fitri).
        Must be supplied explicitly by the caller since it shifts every
        year on the Islamic lunar calendar — never hardcode a fixed
        month/day as a default.
    seasonal_amplitude: how much extra revenue at peak, e.g. 0.4 = +40%
    seasonal_width_days: how spread out the bump is; larger = more gradual
    """
    if seasonal_peak_date is None or seasonal_amplitude == 0.0:
        return np.ones(len(dates))

    peak = pd.to_datetime(seasonal_peak_date)
    days_from_peak = (dates - peak).days.values.astype(float)

    bump = seasonal_amplitude * np.exp(-(days_from_peak ** 2) / (2 * seasonal_width_days ** 2))
    return 1.0 + bump

def generate_merchant(
    days: int = 180,
    base_revenue: float = 500_000,
    trend_slope: float = 0.0,        # daily % change; 0 = flat, positive = growing, negative = declining
    noise_sigma: float = 0.08,
    location_type: str = "residential",
    holiday_calendar=None,
    archetype_label: str = "steady",
    expected_eligible=True,
    start_date: str = "2025-01-01",
    seed: int | None = None,
    seasonal_peak_date=None,
    seasonal_amplitude=0.0,
    seasonal_width_days=10,
) -> dict:
    """
    Generalized merchant generator: trend + weekly seasonality + noise.

    revenue(t) = base_revenue * (1 + trend_slope)^t * weekly_multiplier(t) * lognormal_noise(t)

    archetype_label / expected_eligible are passed in by the caller (see
    archetype configs below) rather than hardcoded, so this one function
    covers steady, growing, declining, and volatile just by varying params.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, periods=days, freq="D")

    # trend: compounding daily growth/decline
    day_index = np.arange(days)
    trend_multiplier = (1 + trend_slope) ** day_index

    weekly_multiplier = get_weekly_multiplier(dates, location_type, holiday_calendar)
    annual_multiplier = get_annual_multiplier(dates, seasonal_peak_date, seasonal_amplitude, seasonal_width_days)
    noise = rng.lognormal(mean=0.0, sigma=noise_sigma, size=days)

    revenue = base_revenue * trend_multiplier * weekly_multiplier * annual_multiplier * noise

    df = pd.DataFrame({"date": dates, "revenue": revenue})

    return {
        "data": df,
        "archetype": archetype_label,
        "expected_eligible": expected_eligible,
        "params": {
            "base_revenue": base_revenue, "trend_slope": trend_slope,
            "noise_sigma": noise_sigma, "location_type": location_type,
            "seasonal_peak_date": seasonal_peak_date, "seasonal_amplitude": seasonal_amplitude,
        },
    }

def apply_shock_event(revenue: np.ndarray, dates, shock_date, duration_days: int, recovery: str = "full") -> np.ndarray:
    """
    Apply an abrupt shock (e.g. fire, forced closure) to an already-generated
    revenue series. This is a post-processing step on top of any continuous
    archetype (steady, growing, etc.), not part of the core trend/seasonality
    model, since a shock is an external event, not a behavior pattern.

    shock_date: date the shock occurs
    duration_days: how long the merchant is at zero/near-zero
    recovery: "full" (returns to original level after), "partial" (returns
        to a reduced level), or "none" (stays at zero for the rest of the series)
    """
    revenue = revenue.copy()
    shock = pd.to_datetime(shock_date)
    shock_idx = (dates == shock).argmax()  # index of the shock date
    end_idx = shock_idx + duration_days

    # zero out revenue during the shock window
    revenue[shock_idx:end_idx] = revenue[shock_idx:end_idx] * 0.02  # near-zero, not literally 0

    if recovery == "full":
        pass  # revenue after end_idx is untouched, already at original level
    elif recovery == "partial":
        revenue[end_idx:] = revenue[end_idx:] * 0.6  # settles at 60% of original level
    elif recovery == "none":
        revenue[end_idx:] = revenue[end_idx:] * 0.02  # stays near-zero permanently
    else:
        raise ValueError(f"Unknown recovery type: {recovery}")

    return revenue

if __name__ == "__main__":
    result = generate_merchant(seed=42, **ARCHETYPE_CONFIGS["seasonal"])
    print(result["data"].head())
    print(f"\nArchetype: {result['archetype']}, params: {result['params']}")
