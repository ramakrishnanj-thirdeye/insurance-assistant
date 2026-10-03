-- Spec 01, step 2/3: silver = typed tables + derived business columns at the as-of date.
-- Needs: SET VARIABLE as_of, high_value. Split from specs/reference/warehouse.sql.

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
