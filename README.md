# QRIS Synthetic Data Generation

A generator of synthetic, QRIS-style transaction histories for Indonesian MSME merchants. Each
merchant follows a defined behavioural archetype (steady, growing, declining, volatile,
seasonal, event-based), optionally with a temporary closure, and is written to its own CSV file
of individual transactions together with a ground-truth label.

It is the data source for the companion project `qris-credit-scoring-engine`. **All data is
synthetic**; no real merchants, transactions or proprietary schemas are used or included.

## Why this exists

The credit scoring engine needs merchant transaction histories to be tested against, and real
QRIS data is private and cannot be shared. This project produces stand-in data whose behaviour
is known in advance, so the engine can be checked against cases where the expected outcome is
understood: a steady warung should pass, a declining shop should be flagged, a bazaar vendor
with long idle periods is a deliberately hard case.

The generator is designed separately from the engine. Each archetype's behaviour and parameters
are written down in [`archetypes.md`](archetypes.md) from domain reasoning first, before any
scoring threshold exists, so the engine's thresholds are not tuned to fit the generator
(avoiding circular validation).

## Quick start

Requires Python 3.10 or newer (developed on 3.14).

```bash
git clone https://github.com/regensa18/qris_synthetic_data_generation.git
cd qris_synthetic_data_generation

python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python generator.py
```

This writes ten merchant files, one year each (2025-01-01 to 2025-12-31):

```
synthetic_merchants/               7 merchants, one per archetype/business combination
synthetic_merchants_with_shock/    3 merchants with a temporary or permanent closure
```

Both folders are git-ignored; run the generator to recreate them. The core generator needs only
`numpy` and `pandas`; the rest of `requirements.txt` supports the exploration notebooks.

## Usage

To generate a single merchant from Python:

```python
from generator import generate_and_save_merchant

path = generate_and_save_merchant(
    output_dir="synthetic_merchants",
    archetype_name="steady",           # steady | growing | declining | volatile | seasonal | event_based
    business_type="warung_sembako",    # see "Business types" below
    merchant_business_scale="UMI",     # UMI | UKE | UME
    location_type="residential",       # residential | office_district | attraction | market
    days=365,
    start_date="2025-01-01",
    seed=1,
    # optional temporary closure (continuous archetypes only)
    shock_date="2025-04-10",
    shock_duration_days=18,
    shock_recovery="full",             # full | partial | none
)
```

The merchant ID, and so the filename, defaults to
`SYN-<archetype>-<business_type>-<scale>-<seed>`, for example
`SYN-steady-warung_sembako-UMI-1.csv`.

To change the set of merchants produced by `python generator.py`, edit the
`merchants_to_generate` and `merchants_with_shock_to_generate` lists at the bottom of
`generator.py`.

### Output format

One CSV per merchant, one row per transaction:

| Column | Notes |
|---|---|
| `merchant_id` | Same value on every row of the file |
| `date` | `YYYY-MM-DD`; daily granularity, no time of day |
| `amount` | Transaction amount in IDR, greater than 0 |
| `type` | Always `credit` |
| `pop_name` | Display name, such as `Toko Sembako MI-1` |
| `rrn` | Random 12-digit reference number |
| `mcc` | Merchant Category Code (ISO 18245) for the business type |
| `merchant_business_scale` | `UMI`, `UKE` or `UME` |
| `business_type` | Generator business type key |
| `archetype` | Ground-truth archetype |
| `expected_eligible` | Ground-truth label: `True`, `False` or an `ambiguous — ...` note |
| `shock_date`, `shock_duration_days`, `shock_recovery` | Only present when a closure was applied |

```csv
merchant_id,date,amount,type,pop_name,rrn,mcc,merchant_business_scale,business_type,archetype,expected_eligible
SYN-steady-warung_sembako-UMI-1,2025-01-01,56880.82,credit,Toko Sembako MI-1,299177239673,5411,UMI,warung_sembako,steady,True
SYN-steady-warung_sembako-UMI-1,2025-01-01,8601.74,credit,Toko Sembako MI-1,232701153122,5411,UMI,warung_sembako,steady,True
```

A day with no sales (a closure, or a non-event day for a bazaar vendor) has no rows at all,
which is how it would appear in a real QRIS history.

The schema uses only fields from the public EMVCo Merchant-Presented QR specification and
Indonesia's public QRIS implementation, never any company's internal schema. The reasoning is
in `archetypes.md`.

## How a merchant is generated

Generation happens in two steps: a daily revenue series, then the split of each day into
individual transactions.

```
archetype + scale + location  ->  daily revenue  ->  (optional) closure  ->  transactions  ->  CSV
```

**1. Daily revenue.** For the continuous archetypes:

```
revenue(t) = base_revenue × trend(t) × weekly(t) × annual(t) × noise(t)
```

- `trend(t)`: compounding daily change, `(1 + trend_slope) ^ t`.
- `weekly(t)`: the day-of-week shape set by `location_type`.
- `annual(t)`: a smooth Gaussian bump around a seasonal peak (used by `seasonal`).
- `noise(t)`: log-normal daily noise with the archetype's `noise_sigma`.

Event-based merchants use a different mechanism: zero revenue every day, except inside a few
randomly placed, non-overlapping event windows.

**2. Transactions.** Each trading day gets a Poisson-distributed number of transactions (mean
set by the business scale), and the day's revenue is split between them with log-normal weights,
so most transactions are small with an occasional large one. The amounts in a day sum to that
day's revenue.

## Archetypes

| Archetype | Mechanism | Default parameters | `expected_eligible` |
|---|---|---|---|
| `steady` | Flat trend, low noise | slope 0, sigma 0.08 | `True` |
| `growing` | Positive trend | +0.25% per day, sigma 0.10 | `True` |
| `declining` | Negative trend | −0.25% per day, sigma 0.10 | `False` |
| `volatile` | Flat trend, high noise | slope 0, sigma 0.45 | ambiguous |
| `seasonal` | Flat trend, annual bump | +50% at peak (2025-03-31, Lebaran), width 10 days, sigma 0.10 | `True` |
| `event_based` | Zero baseline, revenue only in event windows | 4 events of 2 to 5 days, about Rp1.5M per event day | ambiguous |

`volatile` and `event_based` are intentionally ambiguous. They are the cases where a naive
"consistent daily revenue" rule gives the wrong answer, and where the scoring engine's judgment
is actually tested. An event-based merchant's volatility is structured (predictable given the
event dates), not noise, so it is kept as its own archetype rather than folded into `volatile`.

### Location type

Location changes the weekly shape and applies to every archetype except `event_based`:

| `location_type` | Weekend (Sat–Sun) | Weekday |
|---|---|---|
| `residential` | ×1.15 | ×1.0 |
| `office_district` | ×0.4 | ×1.0 |
| `attraction` | ×1.7 | ×0.6 |
| `market` | ×1.0 | ×1.0 |

### Business scale

Scales follow the UMKM categories. Usaha besar (`UBE`) is deliberately excluded because it is
not part of UMKM.

| Scale | Base daily revenue | Mean transactions per day | Average transaction |
|---|---|---|---|
| `UMI` (mikro) | Rp350,000 | 12 | about Rp29,000 |
| `UKE` (kecil) | Rp900,000 | 28 | about Rp32,000 |
| `UME` (menengah) | Rp2,800,000 | 75 | about Rp37,000 |

These represent a typical merchant in each category, well below the legal ceilings in PP 7/2021
(for example, up to about Rp5.5 million per day for usaha mikro).

### Business types

| Key | Label | MCC | Typical archetypes |
|---|---|---|---|
| `warung_sembako` | Toko Sembako | 5411 | steady, declining, growing |
| `fried_chicken_stall` | Warung Ayam Goreng | 5814 | steady, seasonal, growing |
| `coffee_shop` | Kedai Kopi | 5812 | steady, growing, volatile |
| `photocopy_shop` | Fotokopi & Percetakan | 7338 | steady, declining |
| `bazaar_vendor` | Pedagang Bazaar | 5399 | event_based |

The typical archetypes are documentation only; the generator does not enforce them.

### Temporary closures (shocks)

A shock models an abrupt closure such as a fire, renovation or illness. From `shock_date`, the
merchant has zero transactions for `shock_duration_days`. Afterwards:

| `shock_recovery` | After the closure |
|---|---|
| `full` | Sales return to their earlier level |
| `partial` | Sales settle at 60% of their earlier level |
| `none` | The merchant never reopens; the data simply ends at the shock date |

Shocks apply to continuous archetypes only, not to `event_based`. The default run produces:

| File | Closure | Recovery |
|---|---|---|
| `SYN-steady-warung_sembako-UMI-1` | 18 days from 2025-04-10 | full |
| `SYN-steady-coffee_shop-UKE-2` | 7 days from 2025-07-11 | partial |
| `SYN-seasonal-fried_chicken_stall-UMI-3` | 5 days from 2025-10-11 | none |

## Project layout

```
generator.py           archetype, scale and business configs; all generation functions; default run
archetypes.md          design document: archetype reasoning, schema sources, open questions
exploration.ipynb      notebooks used to develop and visually check the generator
exploration_new.ipynb
requirements.txt
```

More detail on the reasoning behind each archetype and schema field:
[`archetypes.md`](archetypes.md).

## Use with the credit scoring engine

The fixtures in `qris-credit-scoring-engine/tests/fixtures/` come from this generator. The
engine reads the required columns (`merchant_id`, `date`, `amount`, `rrn`) and ignores the
label columns. Because the files cover 2025, assess them with the end of that period as the
assessment date:

```bash
python main.py path/to/SYN-steady-warung_sembako-UMI-1.csv --as-of 2025-12-31
```

The `expected_eligible` label is a sanity check of the engine's behaviour, not a measure of its
accuracy.

## Limitations

- Parameters come from domain reasoning, not calibration against real QRIS data or Bank
  Indonesia aggregate figures. That refinement is still open (see `archetypes.md`).
- Only the daily revenue series is reproducible from `seed`. Daily transaction counts, the split
  into amounts, and `rrn` values are drawn without the seed, so re-running produces different
  individual transactions.
- `expected_eligible` reflects the archetype only. A closure does not change the label, so a
  seasonal merchant that never reopens is still labelled `True`.
- The seasonal peak date is fixed at 2025-03-31 and must be updated by hand for other years.
- Holiday-aware weekly patterns exist in `get_weekly_multiplier` but are not exposed through
  `generate_and_save_merchant`.
- Event-based merchants ignore business scale for revenue (a fixed Rp1.5M per event day) and
  ignore location type.
- Zero QRIS activity means no income visible through QRIS, not no income. A bazaar vendor may
  sell online or by bank transfer between events; the generator does not model other channels.
- The schema fields listed as cosmetic in `archetypes.md` (`nmid`, `mpan`, `terminal_id`,
  `merchant_city`, and others) are not generated yet.
- Daily granularity only; there are no transaction timestamps.

## Disclaimer

This is a research and portfolio project. The data it produces is synthetic, does not describe
any real merchant, and is not derived from any company's internal systems or data.
