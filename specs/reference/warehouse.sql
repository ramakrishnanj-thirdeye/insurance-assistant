-- Reference SQL for spec 01 (warehouse). Tested on DuckDB 1.5 against the delivered dataset.
-- Preconditions (set by src/insurai/ingest/build_warehouse.py before running this file):
--   SET VARIABLE as_of      = DATE '2026-10-01';       -- settings.as_of_date
--   SET VARIABLE high_value = 236053;                  -- settings.thresholds.high_value_inr
--   SET VARIABLE raw_dir    = 'data/raw';              -- settings.paths.raw_dir
--   ref.required_documents and ref.diagnosis_coverage loaded from YAML (spec 01 §Reference tables)

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

-- ---------- bronze: CSVs as delivered, explicit types ----------
CREATE OR REPLACE TABLE bronze.customers AS
SELECT * FROM read_csv(getvariable('raw_dir') || '/customers.csv', header = true,
  columns = {'customer_id':'VARCHAR','customer_name':'VARCHAR','age':'INTEGER','gender':'VARCHAR','city':'VARCHAR',
             'state':'VARCHAR','customer_since':'DATE','kyc_status':'VARCHAR','risk_segment':'VARCHAR'});

CREATE OR REPLACE TABLE bronze.policies AS
SELECT * FROM read_csv(getvariable('raw_dir') || '/policies.csv', header = true,
  columns = {'policy_id':'VARCHAR','customer_id':'VARCHAR','policy_type':'VARCHAR','product_name':'VARCHAR',
             'policy_start_date':'DATE','policy_end_date':'DATE','sum_insured':'BIGINT','annual_premium':'BIGINT',
             'policy_status':'VARCHAR','co_pay_pct':'INTEGER','deductible':'BIGINT','waiting_period_days':'INTEGER'});

CREATE OR REPLACE TABLE bronze.claims AS
SELECT * FROM read_csv(getvariable('raw_dir') || '/claims.csv', header = true,
  columns = {'claim_id':'VARCHAR','customer_id':'VARCHAR','policy_id':'VARCHAR','policy_type':'VARCHAR',
             'claim_date':'DATE','claim_amount':'BIGINT','claim_status':'VARCHAR','approved_amount':'BIGINT',
             'diagnosis_or_loss_type':'VARCHAR','hospital_id':'VARCHAR','fraud_risk_score':'DOUBLE',
             'manual_review_flag':'INTEGER','rejection_or_adjustment_reason':'VARCHAR'});

CREATE OR REPLACE TABLE bronze.claim_documents AS
SELECT * FROM read_csv(getvariable('raw_dir') || '/claim_documents.csv', header = true,
  columns = {'claim_id':'VARCHAR','document_type':'VARCHAR','upload_status':'VARCHAR',
             'verification_status':'VARCHAR','file_type':'VARCHAR'});

CREATE OR REPLACE TABLE bronze.hospitals AS
SELECT * FROM read_csv(getvariable('raw_dir') || '/hospitals.csv', header = true,
  columns = {'hospital_id':'VARCHAR','hospital_name':'VARCHAR','city':'VARCHAR','network_status':'VARCHAR','specialty':'VARCHAR'});

CREATE OR REPLACE TABLE bronze.customer_interactions AS
SELECT * FROM read_csv(getvariable('raw_dir') || '/customer_interactions.csv', header = true,
  columns = {'interaction_id':'VARCHAR','customer_id':'VARCHAR','claim_id':'VARCHAR','interaction_date':'DATE',
             'channel':'VARCHAR','intent':'VARCHAR','sentiment':'VARCHAR','resolution_status':'VARCHAR'});

-- ---------- silver: typed + derived business columns ----------
CREATE OR REPLACE TABLE silver.customers AS SELECT * FROM bronze.customers;
CREATE OR REPLACE TABLE silver.hospitals AS SELECT * FROM bronze.hospitals;
CREATE OR REPLACE TABLE silver.claim_documents AS SELECT * FROM bronze.claim_documents;

-- interactions.customer_id disagrees with the claim owner on 179,999 of 180,000 rows (ADR-008):
-- keep it for audit as logged_customer_id; ownership always comes from the claim.
CREATE OR REPLACE TABLE silver.customer_interactions AS
SELECT i.interaction_id, i.claim_id, c.customer_id AS claim_owner_id, i.customer_id AS logged_customer_id,
       i.interaction_date, i.channel, i.intent, i.sentiment, i.resolution_status,
       (i.interaction_date < c.claim_date) AS before_claim_date
FROM bronze.customer_interactions i JOIN bronze.claims c USING (claim_id);

-- Continuous cover: back-to-back policies of the same customer and product form one chain.
CREATE OR REPLACE TABLE silver.policies AS
WITH ordered AS (
  SELECT p.*, lag(policy_end_date) OVER w AS prev_end
  FROM bronze.policies p
  WINDOW w AS (PARTITION BY customer_id, product_name ORDER BY policy_start_date, policy_id)
), chained AS (
  SELECT *, sum(CASE WHEN prev_end IS NULL OR policy_start_date > prev_end + 1 THEN 1 ELSE 0 END)
              OVER (PARTITION BY customer_id, product_name ORDER BY policy_start_date, policy_id) AS chain_no
  FROM ordered
), derived AS (
  SELECT policy_id, customer_id, policy_type, product_name, policy_start_date, policy_end_date, sum_insured,
         annual_premium, policy_status, co_pay_pct, deductible, waiting_period_days,
         min(policy_start_date) OVER (PARTITION BY customer_id, product_name, chain_no) AS continuous_cover_start,
         CASE WHEN policy_status = 'Cancelled'                  THEN 'Cancelled'
              WHEN getvariable('as_of') < policy_start_date     THEN 'Not Started'
              WHEN getvariable('as_of') > policy_end_date       THEN 'Lapsed'
              ELSE 'In Force' END AS effective_status,
         (policy_end_date - getvariable('as_of')) AS days_to_expiry
  FROM chained
)
SELECT *, ((policy_status = 'Active'  AND effective_status <> 'In Force')
        OR (policy_status = 'Expired' AND effective_status =  'In Force')) AS status_conflict
FROM derived;

CREATE OR REPLACE TABLE silver.claims AS
SELECT c.*, p.product_name,
       (c.claim_date BETWEEN p.policy_start_date AND p.policy_end_date)                 AS in_policy_period,
       (c.claim_date - p.policy_start_date)                                            AS days_since_policy_start,
       (c.claim_date - p.continuous_cover_start)                                       AS days_since_cover_start,
       ((c.claim_date - p.policy_start_date) BETWEEN 0 AND p.waiting_period_days - 1)  AS within_schedule_waiting,
       CAST(round(greatest(0, least(c.claim_amount, p.sum_insured) - p.deductible)
                  * (1 - p.co_pay_pct / 100.0)) AS BIGINT)                             AS expected_payable,  -- ADR: deductible first
       (c.claim_amount > getvariable('high_value'))                                    AS high_value
FROM bronze.claims c JOIN silver.policies p ON p.policy_id = c.policy_id;

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
