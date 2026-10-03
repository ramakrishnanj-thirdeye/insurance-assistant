# ADR-008 Interactions join to claims on claim_id only
Status: accepted (open decision #2 defaulted)

**Context.** In customer_interactions, customer_id differs from the referenced claim's owner on 179,999 of 180,000 rows.
**Decision.** Ownership and joins use claim_id → claims.customer_id (`claim_owner_id`). The raw column is kept as `logged_customer_id`, blocked in the semantic layer and never used for access control.
**Consequences.** A customer never sees interactions about someone else's claim; analytics by customer go through claims.
**Alternatives.** Join on customer_id and ignore claim_id (breaks "interactions about this claim", the more common question).
