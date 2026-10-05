---
id: templates
version: 0.2.1
---
## claim_status_fast_path
Claim {claim_id} is **{claim_status}**{approved_clause}. It was filed on {claim_date} for {claim_amount} under {product_name}. [claims:{claim_id}]
(approved_clause = ", with {approved_amount} approved" when approved_amount > 0)

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

## analytics_unavailable
Portfolio analytics (counts, rates and trends) are not available in this assistant yet.

## intents_truncated
You asked about {count} things; I answered the first {max}. Ask again for the rest.

## abstain_heading
Here is what the records show:

## clarification_policy
Which policy do you mean? Give the policy ID (like POL100001).
