"""
Data model for InsureEase Claims Intake Agent.

Plain dataclasses, no external dependencies. This is the shared vocabulary
that tools.py, the Rung 4 workflow, and the (future) Rung 5 agent all read
from. Kept deliberately simple: dicts-in, dicts-out at the tool boundary,
so it mirrors what a real LLM tool-call interface looks like.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PolicyStatus(str, Enum):
    ACTIVE = "active"
    LAPSED = "lapsed"
    CANCELLED = "cancelled"


class CoverageType(str, Enum):
    AUTO_COMPREHENSIVE = "auto_comprehensive"
    AUTO_LIABILITY_ONLY = "auto_liability_only"
    HOME_STANDARD = "home_standard"


class ClaimStatus(str, Enum):
    REPORTED = "reported"
    UNDER_REVIEW = "under_review"
    ESCALATED = "escalated"


@dataclass
class Policy:
    policy_id: str
    holder_name: str
    coverage_type: CoverageType
    status: PolicyStatus
    effective_date: datetime
    expiry_date: datetime
    annual_deductible_usd: float
    deductible_used_usd: float = 0.0
    # exclusions are section keys into the coverage policy doc, e.g. "flood_exclusion"
    exclusions: list[str] = field(default_factory=list)

    def deductible_remaining(self) -> float:
        return round(self.annual_deductible_usd - self.deductible_used_usd, 2)

    def is_active_on(self, when: datetime) -> bool:
        return self.effective_date <= when <= self.expiry_date and self.status == PolicyStatus.ACTIVE


@dataclass
class ClaimEvent:
    """A single prior claim, used for claim_history / frequency signal."""
    claim_id: str
    policy_id: str
    filed_at: datetime
    claim_type: str  # e.g. "collision", "storm_damage", "theft"
    amount_usd: float
    status: str  # "paid", "denied", "pending"


@dataclass
class Claim:
    claim_id: str
    policy_id: str
    reported_at: datetime
    incident_date: datetime
    claim_type: str
    description: str
    loss_location: str | None = None
    status: ClaimStatus = ClaimStatus.REPORTED
    mentions_injury: bool = False
    police_report_filed: bool = False
