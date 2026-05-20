from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
USER_GUIDE_PATH = PROJECT_ROOT / "docs" / "user_guide" / "tag_studio_user_guide.html"

WIZARD_STEPS = [
    "Add Memo",
    "Review Text Quality",
    "Confirm Sections",
    "Set Up Facilities",
    "Tag Credit Review",
    "Tag Outcomes",
    "Quality Check",
    "Download Results",
]

STATUS_LABELS = {
    "Draft": "In Progress",
    "Ready for Review": "Ready for Review",
    "Changes Requested": "Changes Needed",
    "Approved Gold": "Approved for Training Dataset",
    "Exported": "Downloaded",
    "Needs Revalidation": "Needs Revalidation",
}

TAG_CATEGORY_ORDER = [
    "Completeness",
    "Repayment",
    "Financial Analysis",
    "Structure",
    "Collateral",
    "Policy",
    "Risk Assessment",
    "Structure Enhancement",
    "Review Context",
    "Business Risk",
    "Mitigants",
    "Risk Rating",
    "Scoring",
    "Outcome",
]
