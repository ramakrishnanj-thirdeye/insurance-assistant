"""The reviewer decision every eval slice resumes a review pause with: approve, with a neutral note."""

from insurai.rules.schemas import ReviewDecision

AUTO_APPROVE = ReviewDecision(action="approve", note="Reviewed and approved.")
