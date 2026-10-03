---
id: templates
version: 0.1.0
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
