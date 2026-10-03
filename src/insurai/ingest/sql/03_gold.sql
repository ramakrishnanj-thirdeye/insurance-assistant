-- Spec 01, step 3/3: gold = checklist, rule inputs and 360 views. Needs ref.* loaded from config YAML.
-- Split from specs/reference/warehouse.sql.

-- ---------- gold ----------
-- Required vs present vs verified, including required types with no record at all.
CREATE OR REPLACE TABLE gold.claim_doc_checklist AS
WITH req AS (
  SELECT c.claim_id, r.document_type
  FROM silver.claims c
  LEFT JOIN silver.hospitals h ON h.hospital_id = c.hospital_id
  JOIN ref.required_documents r ON r.policy_type = c.policy_type
  WHERE r.condition_field IS NULL
     OR (r.condition_field = 'network_status'         AND list_contains(r.condition_values, h.network_status))
     OR (r.condition_field = 'diagnosis_or_loss_type' AND list_contains(r.condition_values, c.diagnosis_or_loss_type))
)
SELECT coalesce(req.claim_id, d.claim_id)          AS claim_id,
       coalesce(req.document_type, d.document_type) AS document_type,
       (req.claim_id IS NOT NULL)                   AS required,
       d.upload_status, d.verification_status, d.file_type,
       CASE WHEN d.claim_id IS NULL                   THEN 'No record'
            WHEN d.upload_status = 'Missing'          THEN 'Missing'
            WHEN d.verification_status = 'Verified'   THEN 'Verified'
            WHEN d.verification_status = 'Pending'    THEN 'Pending verification'
            WHEN d.verification_status = 'Rejected'   THEN 'Rejected'
       END AS checklist_status
FROM req FULL OUTER JOIN silver.claim_documents d
  ON d.claim_id = req.claim_id AND d.document_type = req.document_type;

-- One row per claim with every input the rules engine needs (spec 07).
CREATE OR REPLACE TABLE gold.claim_facts AS
WITH docs AS (
  SELECT claim_id,
         count(*) FILTER (WHERE required)                                                           AS docs_required,
         count(*) FILTER (WHERE required AND checklist_status IN ('No record', 'Missing'))          AS docs_required_missing,
         count(*) FILTER (WHERE required AND checklist_status = 'Pending verification')             AS docs_required_pending,
         count(*) FILTER (WHERE required AND checklist_status = 'Rejected')                         AS docs_required_rejected,
         list(document_type ORDER BY document_type) FILTER (WHERE required AND checklist_status IN ('No record', 'Missing')) AS missing_doc_types,
         list(document_type ORDER BY document_type) FILTER (WHERE required AND checklist_status = 'Pending verification')    AS pending_doc_types,
         list(document_type ORDER BY document_type) FILTER (WHERE required AND checklist_status = 'Rejected')                AS rejected_doc_types
  FROM gold.claim_doc_checklist GROUP BY claim_id
)
SELECT c.claim_id, c.customer_id, c.policy_id, c.policy_type, c.product_name, c.claim_date, c.claim_amount,
       c.claim_status, c.approved_amount, c.diagnosis_or_loss_type, c.hospital_id, c.fraud_risk_score,
       c.manual_review_flag, c.rejection_or_adjustment_reason,
       p.policy_start_date, p.policy_end_date, p.policy_status, p.effective_status, p.sum_insured, p.co_pay_pct,
       p.deductible, p.waiting_period_days, p.continuous_cover_start,
       c.in_policy_period, c.days_since_policy_start, c.days_since_cover_start, c.within_schedule_waiting,
       c.expected_payable, c.high_value,
       dc.coverage_status, dc.required_waiting_days, dc.waiting_basis, dc.waiting_reason,
       dc.section_no AS coverage_section, dc.coverage_basis, dc.reason AS coverage_reason,
       h.hospital_name, h.network_status, h.specialty AS hospital_specialty, h.city AS hospital_city,
       cu.kyc_status, cu.risk_segment,
       coalesce(d.docs_required, 0)          AS docs_required,
       coalesce(d.docs_required_missing, 0)  AS docs_required_missing,
       coalesce(d.docs_required_pending, 0)  AS docs_required_pending,
       coalesce(d.docs_required_rejected, 0) AS docs_required_rejected,
       d.missing_doc_types, d.pending_doc_types, d.rejected_doc_types
FROM silver.claims c
JOIN silver.policies p        ON p.policy_id = c.policy_id
JOIN silver.customers cu      ON cu.customer_id = c.customer_id
LEFT JOIN silver.hospitals h  ON h.hospital_id = c.hospital_id
LEFT JOIN ref.diagnosis_coverage dc ON dc.product_name = c.product_name AND dc.diagnosis = c.diagnosis_or_loss_type
LEFT JOIN docs d              ON d.claim_id = c.claim_id;

CREATE OR REPLACE VIEW gold.v_claim_360 AS
SELECT f.*, cu.customer_name, cu.age, cu.gender, cu.city AS customer_city, cu.state AS customer_state
FROM gold.claim_facts f JOIN silver.customers cu USING (customer_id);

CREATE OR REPLACE VIEW gold.v_customer_360 AS
SELECT cu.*,
       (SELECT count(*) FROM silver.policies p WHERE p.customer_id = cu.customer_id)                                   AS policies_total,
       (SELECT count(*) FROM silver.policies p WHERE p.customer_id = cu.customer_id AND p.effective_status = 'In Force') AS policies_in_force,
       (SELECT count(*) FROM silver.claims c   WHERE c.customer_id = cu.customer_id)                                   AS claims_total,
       (SELECT count(*) FROM silver.claims c   WHERE c.customer_id = cu.customer_id
                                               AND c.claim_status IN ('Submitted', 'Under Review', 'Pending Documents')) AS claims_open
FROM silver.customers cu;
