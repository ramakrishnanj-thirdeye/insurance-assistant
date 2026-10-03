-- Spec 01, step 1/3: bronze = the delivered CSVs with explicit types. Split from specs/reference/warehouse.sql.
-- Needs: SET VARIABLE raw_dir (set by build_warehouse.py).

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
