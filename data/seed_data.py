"""
Seed data for the four InsureEase test scenarios.

CLM-100: simple, clean claim, active policy -> both rungs should approve advance
CLM-101: lapsed policy boundary case -> tests whether the date-check logic is robust
CLM-102: multi-factor storm damage + exclusion + prior claims -> needs real investigation
CLM-103: injury reported -> must escalate immediately, not process as routine
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from datetime import datetime
from models import Policy, Claim, ClaimEvent, PolicyStatus, CoverageType, ClaimStatus


POLICIES: dict[str, Policy] = {
    "POL-1001": Policy(
        policy_id="POL-1001",
        holder_name="Maria Chen",
        coverage_type=CoverageType.AUTO_COMPREHENSIVE,
        status=PolicyStatus.ACTIVE,
        effective_date=datetime(2026, 1, 1),
        expiry_date=datetime(2026, 12, 31),
        annual_deductible_usd=1000,
        deductible_used_usd=0,
        exclusions=[],
    ),
    "POL-1002": Policy(
        policy_id="POL-1002",
        holder_name="David Okafor",
        coverage_type=CoverageType.AUTO_LIABILITY_ONLY,
        status=PolicyStatus.LAPSED,
        effective_date=datetime(2025, 6, 1),
        expiry_date=datetime(2026, 7, 10),  # lapsed before the incident date below
        annual_deductible_usd=750,
        deductible_used_usd=0,
        exclusions=[],
    ),
    "POL-1003": Policy(
        policy_id="POL-1003",
        holder_name="Priya Natarajan",
        coverage_type=CoverageType.HOME_STANDARD,
        status=PolicyStatus.ACTIVE,
        effective_date=datetime(2026, 1, 1),
        expiry_date=datetime(2026, 12, 31),
        annual_deductible_usd=2000,
        deductible_used_usd=1200,
        exclusions=["flood_exclusion"],
    ),
    "POL-1004": Policy(
        policy_id="POL-1004",
        holder_name="Tom Whitfield",
        coverage_type=CoverageType.AUTO_COMPREHENSIVE,
        status=PolicyStatus.ACTIVE,
        effective_date=datetime(2026, 1, 1),
        expiry_date=datetime(2026, 12, 31),
        annual_deductible_usd=500,
        deductible_used_usd=0,
        exclusions=[],
    ),
    "POL-1005": Policy(
        policy_id="POL-1005",
        holder_name="Angela Ruiz",
        coverage_type=CoverageType.HOME_STANDARD,
        status=PolicyStatus.ACTIVE,
        effective_date=datetime(2026, 1, 1),
        expiry_date=datetime(2026, 12, 31),
        annual_deductible_usd=1500,
        deductible_used_usd=0,
        exclusions=["flood_exclusion"],
    ),
    "POL-1006": Policy(
        policy_id="POL-1006",
        holder_name="Marcus Webb",
        coverage_type=CoverageType.AUTO_COMPREHENSIVE,
        status=PolicyStatus.ACTIVE,
        effective_date=datetime(2026, 1, 1),
        expiry_date=datetime(2026, 12, 31),
        annual_deductible_usd=1000,
        deductible_used_usd=0,
        exclusions=[],
    ),
}


CLAIM_HISTORY: dict[str, list[ClaimEvent]] = {
    "POL-1001": [],
    "POL-1002": [],
    "POL-1003": [
        ClaimEvent("CLM-050", "POL-1003", datetime(2026, 3, 2), "wind_damage", 1800, "paid"),
        ClaimEvent("CLM-071", "POL-1003", datetime(2026, 5, 18), "theft", 900, "paid"),
    ],
    "POL-1004": [],
    "POL-1005": [],  # deliberately empty - isolates the exclusion path from the frequency check
    "POL-1006": [],  # deliberately empty - isolates the ambiguity test from the frequency check
}


CLAIMS: dict[str, Claim] = {
    "CLM-100": Claim(
        claim_id="CLM-100",
        policy_id="POL-1001",
        reported_at=datetime(2026, 7, 15, 10, 30),
        incident_date=datetime(2026, 7, 15, 9, 0),
        claim_type="collision",
        description="Minor fender-bender in a parking lot, other driver at fault, no injuries.",
        loss_location="Denver, CO",
        mentions_injury=False,
        police_report_filed=False,
    ),
    "CLM-101": Claim(
        claim_id="CLM-101",
        policy_id="POL-1002",
        reported_at=datetime(2026, 7, 13, 14, 0),
        incident_date=datetime(2026, 7, 13, 13, 30),  # after policy expiry_date of 2026-07-10
        claim_type="collision",
        description="Rear-ended at a stoplight, bumper damage only.",
        loss_location="Austin, TX",
        mentions_injury=False,
        police_report_filed=True,
    ),
    "CLM-102": Claim(
        claim_id="CLM-102",
        policy_id="POL-1003",
        reported_at=datetime(2026, 7, 20, 8, 0),
        incident_date=datetime(2026, 7, 19, 22, 0),
        claim_type="storm_damage",
        description="Roof shingles torn off and water intrusion into attic during last night's storm.",
        loss_location="Tampa, FL",
        mentions_injury=False,
        police_report_filed=False,
    ),
    "CLM-103": Claim(
        claim_id="CLM-103",
        policy_id="POL-1004",
        reported_at=datetime(2026, 7, 22, 16, 45),
        incident_date=datetime(2026, 7, 22, 16, 0),
        claim_type="collision",
        description="T-boned at an intersection, I have neck pain and possible whiplash.",
        loss_location="Seattle, WA",
        mentions_injury=True,
        police_report_filed=True,
    ),
    "CLM-104": Claim(
        claim_id="CLM-104",
        policy_id="POL-1005",
        reported_at=datetime(2026, 7, 25, 9, 0),
        incident_date=datetime(2026, 7, 24, 20, 0),
        claim_type="storm_damage",
        description="Water intrusion found in the attic after last night's storm, no visible wind damage to the roof.",
        loss_location="Tampa, FL",
        mentions_injury=False,
        police_report_filed=False,
    ),
    "CLM-105": Claim(
        claim_id="CLM-105",
        policy_id="POL-1006",
        reported_at=datetime(2026, 7, 27, 8, 30),
        incident_date=datetime(2026, 7, 27, 6, 0),
        claim_type="theft",
        description="Catalytic converter was stolen overnight while the vehicle was parked on the street.",
        loss_location="Portland, OR",
        mentions_injury=False,
        police_report_filed=True,
    ),
}


# Coverage policy document, split into named sections for search_coverage_policy
# to retrieve against (mirrors how a real policy PDF would be chunked).
COVERAGE_POLICY_SECTIONS: dict[str, str] = {
    "collision_coverage": (
        "Collision coverage applies to damage from impact with another vehicle or "
        "object, regardless of fault, for policyholders with comprehensive or "
        "collision coverage. An emergency advance of up to $500 may be issued "
        "pending full claim review, provided the policy is active as of the "
        "incident date."
    ),
    "liability_only_limits": (
        "Liability-only policies cover damage the policyholder causes to others, "
        "but do not cover repairs to the policyholder's own vehicle. No advance "
        "is payable under liability-only coverage for the policyholder's own "
        "vehicle damage."
    ),
    "storm_and_water_exclusion": (
        "Wind damage to roofing and structures is covered under standard home "
        "policies. However, water intrusion is only covered if it results "
        "directly and immediately from wind-created openings on the same day of "
        "loss. Pre-existing roof conditions or gradual water intrusion are "
        "excluded under the flood_exclusion clause and require adjuster review "
        "before any advance is issued."
    ),
    "claim_frequency_review": (
        "Policies with two or more paid claims within a twelve-month period are "
        "flagged for manual adjuster review before any new advance is approved, "
        "regardless of the apparent validity of the new claim."
    ),
    "lapsed_policy_handling": (
        "No coverage, advance, or benefit of any kind applies to incidents that "
        "occur after a policy's expiry date or during a lapsed status. Claims "
        "filed against a lapsed policy must be declined at intake."
    ),
    "injury_and_bodily_harm": (
        "Any claim involving a reported injury, however minor, must be escalated "
        "to a licensed adjuster and is outside the scope of automated intake "
        "handling. No advance may be issued and no coverage determination may "
        "be communicated to the claimant by the intake agent."
    ),
}
