# Synthetic QRIS Merchant Archetypes — Design Doc

## Purpose

This document defines the intended behavior of each synthetic merchant archetype before any code is written. It exists so that later modeling choices (trend slope, seasonality shape, noise level) are traceable to domain reasoning, so the rule engine's thresholds can be designed independently of this generator, avoiding circular validation (see project brief, "Core principle").

This is a living document. New personas discovered during development should be added here first, with rationale, before being implemented.

---

## Model recap

```
revenue(t) = trend(t) + seasonality(t) + noise(t)
```

- **trend(t)** — long-run slope over the 6–12 month generation window (flat / growing / declining).
- **seasonality(t)** — recurring cyclical shape: weekly (day-of-week effect), monthly (payday effect), annual (Ramadan/Lebaran, holidays).
- **noise(t)** — daily random variation, log-normal distributed.

A new addition below (see "Event-based mechanism") introduces a fourth component for merchants whose revenue isn't well described by continuous trend+seasonality+noise at all.

---

## Location/behavior modifier: weekly seasonality shape

Rather than creating a new archetype for every physical setting, weekly seasonality shape is treated as an **independent modifier** applied on top of the base archetype (steady/seasonal/growing/declining/volatile). This keeps the generator parameterized rather than proliferating near-duplicate archetypes.

`location_type` parameter, affecting the weekly component of seasonality(t):

| location_type | Weekly pattern | Rationale |
|---|---|---|
| `residential` (default) | Mild weekend bump (+~10–15% Sat–Sun) | People home, more local foot traffic. This is the brief's original default assumption. |
| `office_district` | Weekday-high (Mon–Fri lunch-hour concentration), sharp weekend drop (-~40–60% or near-zero Sat–Sun) | Office workers drive weekday lunch demand; offices empty on weekends. |
| `attraction` | Weekend-high (+~50–80% Sat–Sun), weekday-low | Tourist/leisure foot traffic concentrated on days off. Should also respond to Indonesian long-weekends / *cuti bersama* / school holidays as quasi-weekend days — worth a `holiday_calendar` flag if realism matters for a given test case, otherwise Sat–Sun-only is an acceptable simplification. |
| `market` (implicit default for anything not tagged) | Roughly flat by day-of-week | Baseline case, no strong weekly signal. |

**Design note:** `location_type` is orthogonal to the trend-based archetype. A merchant can be `steady + office_district`, `growing + attraction`, etc. This is a deliberate choice to keep the parameter space combinatorial rather than requiring a new archetype definition for every combination.

**Granularity decision:** modeled at daily granularity (higher/lower *total daily* revenue by day-of-week), not intraday. The schema's `date` field (no timestamp) doesn't support hour-level modeling, and the credit-scoring rule engine is expected to reason over day-to-day and week-to-week patterns. Simulating an actual "lunch hour" spike within a day is out of scope unless the rule engine later needs it.

---

## New archetype: Event-based / bazaar merchant

### Why this needs its own mechanism, not just a parameter tweak

The `location_type` modifiers above still assume the merchant operates *every day*, just with day-of-week-dependent volume. Bazaar/event merchants break that assumption entirely; they have long stretches of **zero or near-zero activity**, punctuated by irregular, calendar-driven bursts (a 3-day mall bazaar, a one-day office bazaar, a seasonal market fair). This isn't sinusoidal seasonality; it's intermittent occupancy.

### Proposed mechanism: event calendar

A separate generation step, applied instead of (not on top of) continuous trend+seasonality:

```
event_calendar = [(start_date, end_date, intensity), ...]
```

- Outside any event window: revenue = 0 or near-zero (occasional stray transaction, low probability).
- Inside an event window: revenue follows its own short-lived trend+noise, scaled by `intensity` (e.g. a big mall bazaar vs. a small office bazaar).
- Event windows can be generated either:
  - **Randomly**: Poisson-ish arrival process (e.g. average N events per quarter, each 1–5 days long), for stress-testing the rule engine against irregular but plausible calendars.
  - **Hand-placed**: explicit dates for scenarios needing reproducibility (e.g. always testing against a merchant with exactly 4 events across the window).

### Ground truth label

Not folded into "volatile/erratic." The volatility here is *structured* (predictable given event dates), not noisy. That distinction is the point, and conflating the two would undermine the test case's value.

| Archetype | Description | Expected signal |
|---|---|---|
| `event_based` | Near-zero baseline, revenue concentrated in irregular event windows | Ambiguous by default: `expected_eligible: "ambiguous — requires event-aware scoring"`. A rule engine that naively penalizes low day-to-day consistency would unfairly flag a legitimately viable bazaar merchant; one that correctly identifies event-window consistency (stable revenue *within* events, reasonable event frequency) should be able to pass it. |

### Why this matters beyond testing

This is a concrete, realistic case where "consistent daily revenue" is the wrong lens entirely. It is directly relevant to the neurosymbolic/rule-engine judgment problem the parent research proposal is about: naive statistical thresholds vs. reasoning that accounts for legitimate structural irregularity. Worth keeping explicit in documentation as an intentional test case, not an incidental edge case.

### Caveat: QRIS-visible baseline vs. actual baseline income

The "near-zero baseline" outside event windows represents **QRIS-visible revenue only**, not necessarily the merchant's actual income during that period. A bazaar/event vendor may run an online store, sell through e-commerce marketplaces (Shopee, Tokopedia), or receive payments via bank transfer or e-wallet channels that never touch QRIS at all. Zero QRIS activity between events does not mean zero income; it means zero income *through this particular data source*.

This case is worth stating explicitly rather than glossing over, because it's a genuine limitation of any credit-scoring approach built solely on QRIS transaction history. It's actually a point in favor of the neurosymbolic research angle: a naive rule engine scoring purely on QRIS revenue would systematically undervalue multi-channel merchants, treating "no QRIS activity" as "no income" when the honest read is "no *visible-to-this-data-source* income." A rule engine capable of reasoning about this distinction, rather than silently conflating the two, is a more defensible, OJK-explainable design. This caveat belongs in the eventual README limitations section, not just this design doc.

**Optional ground-truth metadata:** rather than trying to simulate the merchant's actual off-QRIS revenue (out of scope, this generator only produces QRIS transaction data), attach a boolean label at generation time, e.g. `has_other_revenue_channels: true/false`, independent of the generated transaction records themselves. This enables a future validation check: does the rule engine's explanation correctly avoid implying "this merchant has no income" during non-event periods, versus the more accurate "this merchant has no QRIS-visible income"? A rule engine or explanation layer that gets this distinction right is doing something closer to real credit-officer reasoning than one that doesn't.

---

## Updated archetype table (full)

| Archetype | Description | Mechanism | Expected signal |
|---|---|---|---|
| Steady | Consistent daily revenue, low variance | trend=flat, low noise sigma | Eligible |
| Seasonal | Cyclical spikes (e.g. Ramadan/Lebaran) | trend=flat/growing, annual seasonality component | Eligible (seasonality-aware scoring required) |
| Growing | Gradual upward trend | trend=positive slope | Eligible, possibly favorable |
| Declining | Gradual downward trend | trend=negative slope | Likely not eligible / flagged |
| Volatile/erratic | Inconsistent, unpredictable revenue | high noise sigma, no clear trend | Ambiguous; genuine test case for rule engine judgment |
| Event-based (bazaar) | Near-zero baseline, revenue in irregular event bursts | event_calendar mechanism (replaces continuous trend+seasonality) | Ambiguous; requires event-aware scoring |

Any of the first five archetypes may additionally carry a `location_type` modifier (`residential` / `office_district` / `attraction` / `market`) affecting weekly seasonality shape. `event_based` merchants do not use `location_type`. Their event calendar already encodes where/when they're busy.

---

## Canonical schema — additions from public EMVCo/QRIS documentation

The original canonical schema (`merchant_id`, `date`, `amount`, `type`, `pop_name`, `rrn`) can be extended with additional fields that are publicly documented as part of the EMVCo QR standard QRIS is built on, and Indonesia-specific extensions to it. These are **not** derived from any employer or proprietary source, they come from the open EMVCo Merchant-Presented QR specification and publicly available explainers of QRIS payload structure (e.g. community breakdowns of the standard TLV payload, ISO 18245 for merchant category codes).

Two tiers, since they serve different purposes in the generator:

### Tier 1 — Load-bearing for archetype logic

These fields should actually influence generation behavior, not just sit in the schema for realism:

| Field | Description | Why it matters for archetypes |
|---|---|---|
| `mcc` | Merchant Category Code: 4-digit, ISO 18245-standardized classification of business type | Different business types plausibly have different baseline volatility/seasonality (e.g. a food-stall MCC vs. a retail-goods MCC). Could be used to bias which `location_type`/`archetype` combinations are realistic for a given MCC, or just to make generated merchants feel less arbitrary. |
| `merchant_business_scale` | Indonesia-specific business size category: `UMI` (usaha mikro/micro), `UKE` (usaha kecil/small), `UME` (usaha menengah/medium) | Directly relevant to the BPR/MSME research framing, most of this project's target merchants would be `UMI`/`UKE`. Could bias transaction amount distributions (smaller scale → smaller typical transaction sizes, tighter margins) and give a natural way to filter which archetypes are even plausible for a given scale (e.g. a `UMI` merchant is unlikely to have `growing` archetype driven by "new branch"). |

**Correction (post-implementation):** `merchant_business_scale` should only include `UMI` / `UKE` / `UME`. `UBE` (usaha besar) was mistakenly included in early implementation but is **not** part of UMKM. UMKM stands for Usaha Mikro, Kecil, dan Menengah specifically; usaha besar is a legally distinct category (net worth/revenue exceeding usaha menengah's threshold, uncapped above that). Since the parent research proposal targets BPR credit scoring for MSME merchants specifically, a BPR realistically wouldn't be underwriting usaha besar-scale businesses, including UBE didn't serve the project's framing and was removed. Also removed UBE from `BUSINESS_SCALE_CONFIGS` in `generator.py` for this reason.

**Reference: annual → daily revenue thresholds (PP 7/2021)**

The public annual revenue bands under PP 7/2021 (Pasal 35–36), divided by 365 to get a rough daily ceiling/floor, give a sanity-check range for `base_revenue`:

| Scale | Annual revenue (PP 7/2021) | Implied daily revenue range |
|---|---|---|
| UMI (mikro) | up to Rp2 billion | up to ≈ Rp5.5 million/day |
| UKE (kecil) | Rp2–15 billion | ≈ Rp5.5M – Rp41M/day |
| UME (menengah) | Rp15–50 billion | ≈ Rp41M – Rp137M/day |

Note the large gap between these regulatory ceilings and the generator's actual `base_revenue` defaults (e.g. UMI ≈ Rp350k/day, far below the Rp5.5M/day ceiling). This is intentional: the regulatory bands describe the *legal maximum* a business can earn while still qualifying for that tier, not a typical/median value, most real UMI merchants (a small warung, a food stall) operate far below the ceiling. The generator's defaults are chosen to represent a *typical* small merchant within each tier, not the tier's upper bound, and should be read as "plausible for this category," not "calibrated to this exact regulatory midpoint."

Source: PP No. 7 Tahun 2021 tentang Kemudahan, Pelindungan, dan Pemberdayaan Koperasi dan UMKM, Pasal 35–36.

### Tier 2 — Structural realism only (cosmetic, doesn't drive generation logic)

These make the schema look more authentically QRIS-shaped without needing to affect how data is generated:

| Field | Description | Format notes |
|---|---|---|
| `nmid` | National Merchant ID, assigned by the national QRIS registry (PTEN) | 15 digits, e.g. `ID1022210962133`, can be randomly generated per merchant following this shape |
| `mpan` | Merchant Primary Account Number | 18 digits: 5-digit QRIS BIN (`93600`) + 3-digit acquirer code + 10-digit merchant ID. Structure could actually be reused as the generation scheme for synthetic `merchant_id`s, giving free realism. |
| `terminal_id` | Terminal identifier assigned by the acquirer | Numeric, acquirer-specific format |
| `merchant_city` | Merchant's city | Free text / standard EMVCo field |
| `acquirer_site_info` | Acquirer identifier string | e.g. `ID.CO.SHOPEE.WWW`, `ID.CO.BRI.WWW`. Cosmetic, signals which PSP "issued" the merchant's QR |
| `point_of_initiation_method` | Static vs. dynamic QR indicator | `11` = static (sticker, amount entered by payer), `12` = dynamic (EDC/app-generated, amount pre-filled). Not behaviorally relevant to revenue generation, purely a schema-completeness field. |
| `currency_code` | ISO currency code | `360` for IDR, constant across all records, included for schema completeness only |

**Explicitly not included:** `crc` (payload checksum): relevant only to QR code payload integrity at scan-time, meaningless in a post-transaction record, so omitted as noise.

**Design note on sourcing:** all of the above are grounded in the open EMVCo Merchant-Presented QR specification and Indonesia's public implementation of it, not in any specific PSP's or acquirer's internal transaction-processing schema (e.g. internal status codes, retry/reconciliation logic, or payload wrapper formats used by any particular company's backend). That distinction is deliberate and should be preserved as the project grows: the generator's schema should always be traceable to a public standard, never to an internal system's field names or structure.

---

## Open questions / parking lot for future personas

- Should `attraction` merchants get holiday-calendar awareness (long weekends, school holidays) or is Sat–Sun sufficient for now? *(Deferred, add if a test case specifically needs it.)*
- Should there be a hybrid: a merchant with a `location_type` base pattern that *also* occasionally joins bazaars (e.g. a steady office-district warung that does a side bazaar stall twice a year)? *(Not yet modeled, would require combining continuous + event mechanisms for one merchant. Revisit if this persona comes up.)*
- Placeholder for additional personas discovered during development.

---

## Parameter reference (draft — to be refined against BI aggregate figures per brief step 8)

To be filled in once `generate_merchant()` skeleton exists and can be visually validated:

- Weekly amplitude ranges per `location_type`
- Noise sigma ranges per archetype
- Event frequency/duration distributions for `event_based`
- Trend slope ranges for growing/declining
