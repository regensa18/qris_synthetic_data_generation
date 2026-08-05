import numpy as np
import pandas as pd
import uuid
import os
from typing import TypedDict, Any


class ArchetypeConfig(TypedDict, total=False):
    trend_slope: float
    noise_sigma: float
    archetype_label: str
    expected_eligible: bool | str
    seasonal_peak_date: str | None
    seasonal_amplitude: float
    seasonal_width_days: int


ARCHETYPE_CONFIGS: dict[str, ArchetypeConfig] = {
    "steady":    {"trend_slope": 0.0,     "noise_sigma": 0.08, "archetype_label": "steady",    "expected_eligible": True},
    "growing":   {"trend_slope": 0.0025,  "noise_sigma": 0.10, "archetype_label": "growing",   "expected_eligible": True},
    "declining": {"trend_slope": -0.0025, "noise_sigma": 0.10, "archetype_label": "declining", "expected_eligible": False},
    "volatile":  {"trend_slope": 0.0,     "noise_sigma": 0.45, "archetype_label": "volatile",  "expected_eligible": "ambiguous — genuine test case for rule engine judgment"},
    "seasonal": {
        "trend_slope": 0.0, "noise_sigma": 0.10,
        "seasonal_peak_date": "2025-03-31",  # example Lebaran date, adjust per year generated
        "seasonal_amplitude": 0.5,
        "seasonal_width_days": 10,
        "archetype_label": "seasonal", "expected_eligible": True,
    }
}

BUSINESS_SCALE_CONFIGS = {
    "UMI": dict(base_revenue=350_000,   base_count=12),   # avg ≈ 29,000
    "UKE": dict(base_revenue=900_000,   base_count=28),   # avg ≈ 32,000
    "UME": dict(base_revenue=2_800_000, base_count=75),   # avg ≈ 37,000
    # "UBE": dict(base_revenue=6_500_000, base_count=160),  # avg ≈ 41,000, not going tio include it because it's not the scope of MSMEs
}

# Kept for backward compatibility with earlier notebook cells; prefer
# BUSINESS_SCALE_CONFIGS[scale]["base_count"] going forward.
BUSINESS_SCALE_TRANSACTION_COUNT = {
    scale: cfg["base_count"] for scale, cfg in BUSINESS_SCALE_CONFIGS.items()
}

BUSINESS_TYPES = {
    "warung_sembako":      dict(mcc="5411", label="Toko Sembako",        typical_archetypes=["steady", "declining", "growing"]),
    "fried_chicken_stall": dict(mcc="5814", label="Warung Ayam Goreng",  typical_archetypes=["steady", "seasonal", "growing"]),
    "coffee_shop":         dict(mcc="5812", label="Kedai Kopi",          typical_archetypes=["steady", "growing", "volatile"]),
    "photocopy_shop":      dict(mcc="7338", label="Fotokopi & Percetakan", typical_archetypes=["steady", "declining"]),
    "bazaar_vendor":       dict(mcc="5399", label="Pedagang Bazaar",     typical_archetypes=["event_based"]),
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


# def generate_steady_merchant(
#     days: int = 180,
#     base_revenue: float = 500_000,
#     noise_sigma: float = 0.08,
#     location_type: str = "residential",
#     start_date: str = "2025-01-01",
#     seed: int | None = None,
#     holidays: list[str] | None = None,
# ) -> dict:
#     """
#     Generate a daily revenue series for a 'steady' archetype merchant,
#     with a location_type modifier controlling weekly seasonality shape.

#     revenue(t) = base_revenue * weekly_multiplier(t, location_type) * lognormal_noise(t)

#     Returns a dict bundling the data with its ground-truth labels:
#         {
#             "data": pd.DataFrame with columns [date, revenue],
#             "archetype": "steady",
#             "expected_eligible": True,
#             "params": {...},
#         }
#     """
#     rng = np.random.default_rng(seed)
#     dates = pd.date_range(start_date, periods=days, freq="D")

#     weekly_multiplier = get_weekly_multiplier(dates, location_type, holidays)
#     noise = rng.lognormal(mean=0.0, sigma=noise_sigma, size=days)
#     revenue = base_revenue * weekly_multiplier * noise

#     df = pd.DataFrame({"date": dates, "revenue": revenue})

#     return {
#         "data": df,
#         "archetype": "steady",
#         "expected_eligible": True,
#         "params": {
#             "base_revenue": base_revenue,
#             "noise_sigma": noise_sigma,
#             "location_type": location_type,
#         },
#     }


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
    expected_eligible: bool | str = True,
    start_date: str = "2025-01-01",
    seed: int | None = None,
    seasonal_peak_date=None,
    seasonal_amplitude=0.0,
    seasonal_width_days=10,
    merchant_business_scale: str | None = None,
) -> dict:
    """
    Generalized merchant generator: trend + weekly seasonality + annual seasonality + noise.
 
    merchant_business_scale: optional "UMI"/"UKE"/"UME"/"UBE". If provided,
    OVERRIDES base_revenue with the value from BUSINESS_SCALE_CONFIGS, so
    revenue level stays consistent with the scale's transaction-count config
    (see sample_daily_transaction_counts). If None, base_revenue is used as-is
    and no scale label is attached (caller can still set it manually via
    the returned dict if needed).
    """
    if merchant_business_scale is not None:
        if merchant_business_scale not in BUSINESS_SCALE_CONFIGS:
            raise ValueError(f"Unknown merchant_business_scale: {merchant_business_scale}")
        base_revenue = BUSINESS_SCALE_CONFIGS[merchant_business_scale]["base_revenue"]

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

def apply_shock_event(revenue: np.ndarray, dates, shock_date, duration_days: int, recovery: str = "full"):
    """
    Apply an abrupt shock (e.g. fire, forced closure) to an already-generated
    revenue series.

    Returns (revenue, shock_mask): shock_mask is a boolean array marking
    which days fall inside the shock window. A shut-down merchant genuinely
    processes ZERO QRIS transactions on those days, so downstream transaction generation should
    use shock_mask to skip transaction generation entirely for those days.
    """
    revenue = revenue.copy()
    shock = pd.to_datetime(shock_date)

    if shock not in set(dates):
        raise ValueError(
            f"shock_date {shock_date} is outside the generated date range "
            f"({dates.min().date()} to {dates.max().date()}). "
            f"Adjust shock_date or increase `days` in generate_merchant()."
        )

    shock_idx = (dates == shock).argmax()
    end_idx = min(shock_idx + duration_days, len(revenue))  # clip so it can't run past the series

    shock_mask = np.zeros(len(revenue), dtype=bool)
    shock_mask[shock_idx:end_idx] = True

    # zero out revenue during the shock window
    revenue[shock_idx:end_idx] = 0.0

    if recovery == "full":
        pass  # revenue after end_idx is untouched, already at original level
    elif recovery == "partial":
        revenue[end_idx:] = revenue[end_idx:] * 0.6  # settles at 60% of original level
    elif recovery == "none":
        revenue[end_idx:] = 0.0
        shock_mask[end_idx:] = True  # stays "closed" for the rest of the series
    else:
        raise ValueError(f"Unknown recovery type: {recovery}")

    return revenue, shock_mask

# ---------------------------------------------------------------------------
# Transaction-level splitting
# ---------------------------------------------------------------------------
 
def sample_daily_transaction_count(base_count: int = 12, seed: int | None = None) -> int:
    """
    Poisson-distributed transaction count for a single day. Count data
    (discrete events per day) is standard-modeled as Poisson; base_count
    (lambda) should come from general reasoning about merchant footfall,
    not from any specific real dataset.
    """
    rng = np.random.default_rng(seed)
    return max(1, rng.poisson(lam=base_count))

def sample_daily_transaction_counts(days: int, base_count: int = 12, seed: int | None = None) -> np.ndarray:
    """Vectorized version: one Poisson draw per day across the full series."""
    rng = np.random.default_rng(seed)
    return np.maximum(1, rng.poisson(lam=base_count, size=days))

######
def split_day_into_transactions(daily_revenue, n_transactions, seed=None):
    """
    Split a day's total revenue into n_transactions amounts that sum to it,
    log-normal weighted so most transactions are small with occasional larger ones.
    """
    rng = np.random.default_rng(seed)
    weights = rng.lognormal(mean=0, sigma=0.6, size=n_transactions)
    weights = weights / weights.sum()
    return daily_revenue * weights

def generate_transactions(
    result: dict,
    business_type: str,
    merchant_business_scale: str = "UMI",
    merchant_id: str | None = None,
    shock_mask: np.ndarray | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    """
    Expand a generate_merchant()/generate_event_based_merchant() result dict
    into transaction-level rows matching the canonical schema.

    shock_mask: optional boolean array (from apply_shock_event), same length
    as result["data"]. Days marked True generate ZERO transactions.
    """

    if business_type not in BUSINESS_TYPES:
        raise ValueError(f"Unknown business_type: {business_type}. Options: {list(BUSINESS_TYPES)}")
    if merchant_business_scale not in BUSINESS_SCALE_CONFIGS:
        raise ValueError(f"Unknown merchant_business_scale: {merchant_business_scale}")

    biz = BUSINESS_TYPES[business_type]
    rng = np.random.default_rng(seed)
    df = result["data"]
    base_count = BUSINESS_SCALE_CONFIGS[merchant_business_scale]["base_count"]
    merchant_id = merchant_id or f"SYN{rng.integers(100000, 999999)}"
    pop_name = f"{biz['label']} {merchant_id[-4:]}"

    rows = []
    for i, (_, row) in enumerate(df.iterrows()):
        is_shocked = shock_mask is not None and shock_mask[i]
        if is_shocked:
            continue  # closed this day, zero transactions

        n_tx = sample_daily_transaction_count(base_count=base_count)
        amounts = split_day_into_transactions(row["revenue"], n_tx)

        for amt in amounts:
            rows.append({
                "merchant_id": merchant_id,
                "date": row["date"].strftime("%Y-%m-%d"),
                "amount": round(float(amt), 2),
                "type": "credit",
                "pop_name": pop_name,
                "rrn": str(uuid.uuid4().int)[:12],  # placeholder unique reference
                "mcc": biz["mcc"],
                "merchant_business_scale": merchant_business_scale,
                "business_type": business_type,
            })

    tx_df = pd.DataFrame(rows)
    tx_df["archetype"] = result["archetype"]
    tx_df["expected_eligible"] = str(result["expected_eligible"])
    return tx_df

def generate_and_save_merchant(
    output_dir: str,
    archetype_name: str,
    business_type: str,
    merchant_business_scale: str = "UMI",
    location_type: str = "residential",
    merchant_id: str | None = None,
    days: int = 180,
    start_date: str = "2025-01-01",
    shock_date: str | None = None,
    shock_duration_days: int | None = None,
    shock_recovery: str = "full",
    seed: int | None = None,
) -> str:
    """
    Generates one merchant (continuous archetype or event_based), optionally
    applies a shock_event (e.g. fire, forced closure) to the daily revenue
    series, then expands to transaction-level rows and writes it to its own
    CSV. Returns the filepath written.
 
    shock_date / shock_duration_days: if both provided, apply_shock_event()
    is applied to the merchant's revenue series before transaction splitting.
    Only meaningful for continuous archetypes (steady/growing/declining/
    volatile/seasonal) — not applied to event_based merchants, since their
    near-zero baseline already represents an "off" state and layering a
    second shock mechanism on top isn't a meaningful combination.
    """
    os.makedirs(output_dir, exist_ok=True)

    if archetype_name == "event_based":
        result = generate_event_based_merchant(days=days, start_date=start_date, seed=seed)
        shock_mask = None
    else:
        if archetype_name not in ARCHETYPE_CONFIGS:
            raise ValueError(f"Unknown archetype_name: {archetype_name}")
        cfg = ARCHETYPE_CONFIGS[archetype_name]
        result = generate_merchant(
            merchant_business_scale=merchant_business_scale,
            location_type=location_type,
            days=days,
            start_date=start_date,
            seed=seed,
            **cfg,
        )
 
        shock_mask = None
        # Apply shock_event on top of the continuous archetype, if requested.
        if shock_date is not None and shock_duration_days is not None:
            df = result["data"]
            new_revenue, shock_mask = apply_shock_event(
                df["revenue"].values,
                df["date"],
                shock_date=shock_date,
                duration_days=shock_duration_days,
                recovery=shock_recovery,
            )
            df["revenue"] = new_revenue
            result["params"]["shock_event"] = {
                "shock_date": shock_date,
                "duration_days": shock_duration_days,
                "recovery": shock_recovery,
            }

    merchant_id = merchant_id or f"SYN-{archetype_name}-{business_type}-{merchant_business_scale}-{seed}"
    tx_df = generate_transactions(
        result,
        business_type=business_type,
        merchant_business_scale=merchant_business_scale,
        merchant_id=merchant_id,
        shock_mask=shock_mask,
        seed=seed,
    )

    # Record the shock as a column too, so it's visible directly in the CSV
    # without needing to cross-reference result["params"].
    if shock_date is not None and shock_duration_days is not None:
        tx_df["shock_date"] = shock_date
        tx_df["shock_duration_days"] = shock_duration_days
        tx_df["shock_recovery"] = shock_recovery

    filename = f"{merchant_id}.csv"
    filepath = os.path.join(output_dir, filename)
    tx_df.to_csv(filepath, index=False)

    return filepath

if __name__ == "__main__":

    merchants_to_generate: list[dict[str, Any]] = [
        dict(output_dir = "synthetic_merchants", archetype_name="steady",   business_type="warung_sembako",      merchant_business_scale="UMI", location_type="residential",     seed=1, days=365, start_date="2025-01-01"),
        dict(output_dir = "synthetic_merchants", archetype_name="steady",   business_type="coffee_shop",         merchant_business_scale="UKE", location_type="office_district",  seed=2, days=365, start_date="2025-01-01"),
        dict(output_dir = "synthetic_merchants", archetype_name="growing",  business_type="coffee_shop",         merchant_business_scale="UME", location_type="attraction",       seed=3, days=365, start_date="2025-01-01"),
        dict(output_dir = "synthetic_merchants", archetype_name="declining",business_type="photocopy_shop",      merchant_business_scale="UMI", location_type="market",           seed=4, days=365, start_date="2025-01-01"),
        dict(output_dir = "synthetic_merchants", archetype_name="volatile", business_type="fried_chicken_stall", merchant_business_scale="UKE", location_type="residential",      seed=5, days=365, start_date="2025-01-01"),
        dict(output_dir = "synthetic_merchants", archetype_name="seasonal", business_type="fried_chicken_stall", merchant_business_scale="UMI", location_type="residential",      seed=6, days=365, start_date="2025-01-01"),
        dict(output_dir = "synthetic_merchants", archetype_name="event_based", business_type="bazaar_vendor",    merchant_business_scale="UMI", seed=7, days=365, start_date="2025-01-01"),
    ]

    for config in merchants_to_generate:
        path = generate_and_save_merchant(**config)
        print(f"Wrote {path}")

    # generate and save merchant with shock event (e.g. fire)
    merchants_with_shock_to_generate: list[dict[str, Any]] = [
        dict(
            output_dir="synthetic_merchants_with_shock", 
            archetype_name="steady",   
            business_type="warung_sembako",      
            merchant_business_scale="UMI", 
            location_type="residential",     
            seed=1, 
            shock_date="2025-04-10",
            shock_duration_days=18,
            shock_recovery="full",
            days=365, 
            start_date="2025-01-01",
        ),
        dict(
            output_dir="synthetic_merchants_with_shock", 
            archetype_name="steady",   
            business_type="coffee_shop",         
            merchant_business_scale="UKE", 
            location_type="office_district",  
            seed=2,
            shock_date="2025-07-11",
            shock_duration_days=7,
            shock_recovery="partial",
            days=365, 
            start_date="2025-01-01",
        ),
        dict(
            output_dir="synthetic_merchants_with_shock", 
            archetype_name="seasonal", 
            business_type="fried_chicken_stall", 
            merchant_business_scale="UMI", 
            location_type="residential",      
            seed=3,
            shock_date="2025-10-11",
            shock_duration_days=5,
            shock_recovery="none",
            days=365, 
            start_date="2025-01-01",
        ),
    ]
    
    for config in merchants_with_shock_to_generate:
        path = generate_and_save_merchant(**config)
        print(f"Wrote {path}")
