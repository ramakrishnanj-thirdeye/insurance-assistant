---
id: templates
version: 0.7.0
---
## claim_status
Claim {claim_id} is **{claim_status}**{approved_clause}. It was filed on {claim_date} for {claim_amount} under {product_name}. {label}
(approved_clause = ", with {approved_amount} approved" whenever approved_amount is recorded, ₹0 included. Used by the fast path and by every single claim_status turn, spec 06 template answers.)

## claim_status_reason
Reason on record: {reason}. {label}

## claim_documents_missing
Claim {claim_id} is missing these required documents: {documents}. {label}

## claim_documents_none_missing
No documents are missing for claim {claim_id}. {label}

## claim_documents_pending
Pending verification: {documents}. {label}

## claim_documents_rejected
Rejected documents: {documents}. {label}

## claim_documents_untracked
Not tracked in the document records, so keep them ready: {documents}. {label}

## hospital_check
{hospital_name} ({hospital_id}, {city}) is **{network_status}**. {label}

## hospital_on_claim
The hospital on claim {claim_id} is {hospital_name} ({hospital_id}, {city}), which is **{network_status}**. {labels}

## hospital_none_on_claim
Claim {claim_id} has no hospital on record. {label}

## hospital_alternatives
Network alternatives in {city} for {specialty}:

## policy_of_claim
Claim {claim_id} is on policy {policy_id}. {label}

## policy_details
Policy {policy_id} ({product_name}, {policy_type}) is **{effective_status}**; policy period {policy_start_date} to {policy_end_date}. {label}

## policy_status_conflict
The recorded status, {policy_status}, is out of date; the effective status comes from the policy dates. {label}

## policy_schedule
Sum insured {sum_insured}, annual premium {annual_premium}, waiting period {waiting_period_days} days, co-pay {co_pay_pct}%, deductible {deductible}. {label}

## greeting
Hello! I can help with policy coverage, claim status and documents, and network hospitals. What would you like to check?

## clarification_product
Which product do you mean? {product_list}

## clarification_claim
Which claim do you mean? {claim_list}

## specialist_review_customer
A claims specialist will review this claim before a decision. Final decision depends on complete claim assessment.

## review_decision
Reviewer decision: **{action}**. Reviewer note: {note}

## planner_failure
Sorry, I couldn't work out what you need. Could you rephrase it, naming the claim, policy, hospital or product?

## analytics_rejected
I couldn't answer that with a safe, validated query ({reason}). Try rephrasing it with the measure and the grouping you want.

## analytics_table_heading
The query returned {row_count} rows {label}:

## analytics_more_rows
{more} more rows are in the table below.

## intents_truncated
You asked about {count} things; I answered the first {max}. Ask again for the rest.

## abstain_heading
Here is what the records show:

## clarification_policy
Which policy do you mean? Give the policy ID (like POL100001).

## premise_correction
{claim_id} is {claim_status}, not {premise} {label}.

## customer_message
Here is an update on your claim {claim_id}, which is {claim_status}. Next steps: {steps}. Final decision depends on complete claim assessment.

## guarantee_lead
I can't promise an outcome. Final decision depends on complete claim assessment. {label}

## guarantee_needs_heading
What claim {claim_id} still needs:

## conflict_line
{concept_name}: {schedule_value} {unit} in your policy schedule {schedule_label}; {wording_value} {unit} in the product wording {wording_label}.

## narrative_opening
Claim {claim_id} is {claim_status}; {blockers}; {review} {label}.

## narrative_blocker_one
1 blocker

## narrative_blockers
{n} blockers

## narrative_review_needed
needs human review

## narrative_review_not_needed
doesn't need human review
