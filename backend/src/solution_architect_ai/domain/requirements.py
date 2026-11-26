from enum import StrEnum


class RequirementCategory(StrEnum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    BUSINESS_GOAL = "business_goal"
    SYSTEM_BOUNDARY = "system_boundary"
    STAKEHOLDER = "stakeholder"
    DATA = "data"
    CONSTRAINT = "constraint"
    GAP = "gap"
    CONTRADICTION = "contradiction"


class EvidenceStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class CoverageWarning(StrEnum):
    CROSS_PART_REVIEW = "cross_part_semantic_review_required"
