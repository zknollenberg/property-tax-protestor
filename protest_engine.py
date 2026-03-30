"""
Protest analysis engine.

Implements the Texas Tax Code §41.43 unequal-appraisal strategy:
  If the subject property's appraised value per sqft exceeds the *median*
  appraised value per sqft of a reasonable sample of comparable properties
  in the same CCAD neighborhood, the Appraisal Review Board MUST reduce the
  value to the median level.

No sale prices are required — this uses only the district's own certified
values, which makes the evidence undeniable.

All figures come from live CCAD data.  Nothing is fabricated.
"""

import statistics
from typing import Optional

from models import (
    PropertyInfo,
    ComparableProperty,
    ProtestReport,
)

# Minimum number of comps required to declare a protest viable
MIN_COMPS = 5

# An overassessment is considered actionable only if the subject's $/sqft
# exceeds the median by more than this threshold (to filter noise / rounding)
OVERASSESSMENT_THRESHOLD_PCT = 3.0   # 3 %


def build_report(
    subject: PropertyInfo,
    raw_comps: list[dict],
    effective_tax_rate_pct: float,
    client,          # CCadClient — for map_to_property()
) -> ProtestReport:
    """
    Given a subject property and a list of raw Socrata comp records, return
    a fully populated ProtestReport.

    Parameters
    ----------
    effective_tax_rate_pct:
        The combined effective property-tax rate as a percentage (e.g. 1.8 for
        1.8 %).  Users read this from their most recent Collin County tax bill.
    """

    # ── 1. Convert raw records to typed ComparableProperty objects ─────────────
    typed_comps: list[ComparableProperty] = []
    for raw in raw_comps:
        prop = client.map_to_property(raw)

        # Skip properties with missing sqft (can't compute $/sqft)
        if not prop.bldg_sqft or prop.bldg_sqft <= 0:
            continue
        # Skip properties with zero or negative market value
        if prop.market_value <= 0:
            continue
        # Skip the subject itself
        if prop.account_num == subject.account_num:
            continue

        vpsf = prop.market_value / prop.bldg_sqft

        typed_comps.append(
            ComparableProperty(
                account_num=prop.account_num,
                address=prop.address,
                market_value=prop.market_value,
                bldg_sqft=prop.bldg_sqft,
                yr_built=prop.yr_built,
                neighborhood_cd=prop.neighborhood_cd,
                value_per_sqft=round(vpsf, 2),
            )
        )

    # ── 2. Compute subject's $/sqft ────────────────────────────────────────────
    if not subject.bldg_sqft or subject.bldg_sqft <= 0:
        return ProtestReport(
            subject=subject,
            comps=typed_comps,
            protest_viable=False,
            protest_basis="insufficient_data",
            comps_count=len(typed_comps),
        )

    subject_vpsf = subject.market_value / subject.bldg_sqft

    # ── 3. Require enough comps for a statistically meaningful sample ──────────
    if len(typed_comps) < MIN_COMPS:
        return ProtestReport(
            subject=subject,
            comps=typed_comps,
            subject_value_per_sqft=round(subject_vpsf, 2),
            protest_viable=False,
            protest_basis=(
                f"Only {len(typed_comps)} comparable properties found "
                f"(minimum {MIN_COMPS} required). "
                "Try widening the search by relaxing year-built filters."
            ),
            comps_count=len(typed_comps),
        )

    # ── 4. Sort comps by $/sqft and compute statistics ─────────────────────────
    typed_comps.sort(key=lambda c: c.value_per_sqft)
    vpsf_values = [c.value_per_sqft for c in typed_comps]

    median_vpsf = statistics.median(vpsf_values)
    mean_vpsf   = statistics.mean(vpsf_values)

    # ── 5. Determine whether protest is viable ────────────────────────────────
    overassessment_pct = ((subject_vpsf - median_vpsf) / median_vpsf) * 100
    protest_viable = overassessment_pct > OVERASSESSMENT_THRESHOLD_PCT

    # ── 6. Compute recommended value and savings ──────────────────────────────
    recommended_value: Optional[float] = None
    potential_reduction: Optional[float] = None
    estimated_savings: Optional[float] = None

    if protest_viable:
        recommended_value  = round(median_vpsf * subject.bldg_sqft, 2)
        potential_reduction = round(subject.market_value - recommended_value, 2)
        estimated_savings   = round(
            potential_reduction * (effective_tax_rate_pct / 100), 2
        )

    # ── 7. Build basis string ─────────────────────────────────────────────────
    if protest_viable:
        basis = (
            f"Unequal Appraisal — Texas Tax Code §41.43. "
            f"Subject appraised at ${subject_vpsf:,.2f}/sqft vs. median "
            f"${median_vpsf:,.2f}/sqft for {len(typed_comps)} comparable "
            f"properties in neighborhood {subject.neighborhood_cd} "
            f"({overassessment_pct:+.1f}% above median)."
        )
    else:
        basis = (
            f"Subject appraised at ${subject_vpsf:,.2f}/sqft vs. median "
            f"${median_vpsf:,.2f}/sqft ({overassessment_pct:+.1f}%). "
            f"Difference is within the {OVERASSESSMENT_THRESHOLD_PCT}% noise "
            f"threshold — protest may not yield a reduction."
        )

    return ProtestReport(
        subject=subject,
        comps=typed_comps,
        subject_value_per_sqft=round(subject_vpsf, 2),
        median_comp_value_per_sqft=round(median_vpsf, 2),
        mean_comp_value_per_sqft=round(mean_vpsf, 2),
        recommended_value=recommended_value,
        potential_reduction=potential_reduction,
        estimated_savings=estimated_savings,
        protest_viable=protest_viable,
        protest_basis=basis,
        comps_count=len(typed_comps),
    )


def format_protest_letter(report: ProtestReport, owner_contact: dict) -> str:
    """
    Return a plain-text protest letter the owner can print and submit.
    All values are taken directly from `report` — no invented numbers.
    """
    subj = report.subject
    today = owner_contact.get("date", "")
    owner_name = owner_contact.get("name") or subj.owner_name or "[OWNER NAME]"
    phone  = owner_contact.get("phone", "[PHONE]")
    email  = owner_contact.get("email", "[EMAIL]")

    comp_rows = []
    for c in report.comps[:15]:   # show up to 15 comps in the letter
        comp_rows.append(
            f"  {c.address:<45} {c.bldg_sqft:>7,.0f} sqft   "
            f"${c.market_value:>12,.0f}   ${c.value_per_sqft:>8.2f}/sqft"
        )
    comp_table = "\n".join(comp_rows) if comp_rows else "  (none found)"

    letter = f"""
Collin Central Appraisal District
250 W. Eldorado Pkwy
McKinney, TX 75069

Date: {today}

RE: Protest of Appraised Value — Tax Year {subj.data_year}
    Property Address : {subj.address}, {subj.city} {subj.zip_code}
    CCAD Account No. : {subj.account_num}

To Whom It May Concern:

I, {owner_name}, hereby protest the appraised value of the above-referenced
property pursuant to Texas Tax Code §41.43 (Unequal Appraisal).

CURRENT APPRAISED VALUE: ${subj.market_value:,.0f}
  Land value         : ${subj.land_value:,.0f}
  Improvement value  : ${subj.improvement_value:,.0f}
  Building size      : {subj.bldg_sqft:,.0f} sqft
  Year built         : {subj.yr_built or "N/A"}
  Neighborhood code  : {subj.neighborhood_cd}

APPRAISAL PER SQFT (subject): ${report.subject_value_per_sqft:,.2f}
MEDIAN APPRAISAL PER SQFT
  ({report.comps_count} comparable properties): ${report.median_comp_value_per_sqft:,.2f}

The subject property is appraised {((report.subject_value_per_sqft - report.median_comp_value_per_sqft) / report.median_comp_value_per_sqft * 100):+.1f}% above the median
of comparable residential properties in the same CCAD neighborhood, as
required by §41.43(b) to establish unequal appraisal.

REQUESTED VALUE: ${report.recommended_value:,.0f}
  (median $/sqft × {subj.bldg_sqft:,.0f} sqft = ${report.median_comp_value_per_sqft:,.2f} × {subj.bldg_sqft:,.0f})

COMPARABLE PROPERTIES (from CCAD appraisal roll, data.texas.gov):
{"Address":<45} {"Size":>7}        {"Value":>14}   {"$/sqft":>10}
{"-"*80}
{comp_table}

All values above are taken directly from the Collin Central Appraisal
District's certified appraisal roll as published on the Texas Open Data
Portal (data.texas.gov, dataset 7ugx-vxwc).  No third-party estimates
or sale prices have been used.

Sincerely,

{owner_name}
{subj.address}
{subj.city}, TX {subj.zip_code}
Phone : {phone}
E-mail: {email}
""".strip()

    return letter
