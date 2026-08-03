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
    seed: int | None = None,
) -> pd.DataFrame:
    """
    Expand a generate_merchant()/generate_event_based_merchant() result dict
    into transaction-level rows matching the canonical schema.
 
    business_type: key into BUSINESS_TYPES (e.g. "warung_sembako",
        "coffee_shop") — drives mcc and pop_name label.
    merchant_business_scale: key into BUSINESS_SCALE_CONFIGS — drives
        transaction count per day.
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
    for _, row in df.iterrows():
        n_tx = sample_daily_transaction_count(base_count=base_count)
        amounts = split_day_into_transactions(row["revenue"], n_tx)

        for amt in amounts:
            rows.append({
                "merchant_id": merchant_id,
                "date": row["date"].strftime("%Y-%m-%d"),
                "amount": round(float(amt), 2),
                "type": "credit",
                "pop_name": f"POP-{merchant_id}",
                "rrn": str(uuid.uuid4().int)[:12],  # placeholder unique reference
                "mcc": "5812",  # example: eating places/restaurants
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
    business_type: str = "coffee_shop",
    merchant_business_scale: str = "UMI",
    location_type: str = "residential",
    merchant_id: str | None = None,
    seed: int | None = None,
) -> str:
    """
    Generates one merchant (continuous archetype or event_based), expands to
    transaction-level rows using business_type + merchant_business_scale,
    and writes it to its own CSV. Returns the filepath written.
    """
    os.makedirs(output_dir, exist_ok=True)

    if archetype_name == "event_based":
        result = generate_event_based_merchant(seed=seed)
    else:
        if archetype_name not in ARCHETYPE_CONFIGS:
            raise ValueError(f"Unknown archetype_name: {archetype_name}")
        cfg = ARCHETYPE_CONFIGS[archetype_name]
        result = generate_merchant(
            merchant_business_scale=merchant_business_scale,
            location_type=location_type,
            seed=seed,
            **cfg,
        )

    merchant_id = merchant_id or f"SYN-{archetype_name}-{merchant_business_scale}-{seed}"
    tx_df = generate_transactions(
        result,
        business_type=business_type,
        merchant_business_scale=merchant_business_scale,
        merchant_id=merchant_id,
        seed=seed,
    )

    filename = f"{merchant_id}.csv"
    filepath = os.path.join(output_dir, filename)
    tx_df.to_csv(filepath, index=False)

    return filepath

if __name__ == "__main__":
    # result = generate_merchant(seed=42, **ARCHETYPE_CONFIGS["seasonal"])
    # print(result["data"].head())
    # print(f"\nArchetype: {result['archetype']}, params: {result['params']}")

    # result = generate_merchant(seed = 42, **ARCHETYPE_CONFIGS["steady"])
    # df = result["data"]

    # df["revenue"] = apply_shock_event(df["revenue"].values, df["date"], shock_date="2025-04-10", duration_days=18, recovery="full")
    # print(df.head())

    # result["params"]["shock_event"] = {"shock_date": "2025-04-10", "duration_days": 18, "recovery": "full"}

    # counts = sample_daily_transaction_counts(30, base_count=BUSINESS_SCALE_TRANSACTION_COUNT["UMI"], seed=1)
    # print(f"\nExample 30-day transaction counts (UMI): {counts}")
    # print(f"min={counts.min()}, max={counts.max()}, mean={counts.mean():.1f}")

    # result = generate_merchant(merchant_business_scale="UKE", seed=42, **ARCHETYPE_CONFIGS["steady"])

    # tx_df = generate_transactions(result, merchant_business_scale="UKE", seed=1)
    # tx_df.to_csv("synthetic_merchant_steady_UKE.csv", index=False)
    # tx_df.head(10)

    # output_dir = "synthetic_merchants"

    # merchants_to_generate: list[dict[str, Any]] = [
    #     {"archetype_name": "steady", "merchant_business_scale": "UMI", "location_type": "residential", "seed": 1},
    #     {"archetype_name": "steady", "merchant_business_scale": "UKE", "location_type": "office_district", "seed": 2},
    #     {"archetype_name": "growing", "merchant_business_scale": "UME", "location_type": "attraction", "seed": 3},
    #     {"archetype_name": "declining", "merchant_business_scale": "UMI", "location_type": "market", "seed": 4},
    #     {"archetype_name": "volatile", "merchant_business_scale": "UKE", "location_type": "residential", "seed": 5},
    #     {"archetype_name": "seasonal", "merchant_business_scale": "UMI", "location_type": "residential", "seed": 6},
    #     {"archetype_name": "event_based", "merchant_business_scale": "UMI", "seed": 7},
    # ]

    # for config in merchants_to_generate:
    #     path = generate_and_save_merchant(output_dir, **config)
    #     print(f"Wrote {path}")

    path = generate_and_save_merchant(
        output_dir="synthetic_merchants",
        archetype_name="steady",
        business_type="coffee_shop",
        merchant_business_scale="UKE",
        location_type="office_district",
        seed=42,
    )
    print(f"Wrote {path}")
