# claim_analysis draft items: sign-off checklist

Labels were derived by `python -m insurai.eval.claim_labels` from silver.* and ref.* in
plain Python, independently of the rules engine. Check each claim against the raw data, then
tick the box and remove the `draft` tag from the item in claim_analysis.jsonl.

## CA004 CLM300027: Cancelled policy (R02 fail)

- Question: "Analyze claim CLM300027."
- Facts: {"product_name": "Global Travel Secure", "diagnosis_or_loss_type": "Medical Emergency", "claim_status": "Partially Approved", "claim_amount": 24910, "approved_amount": 15697, "expected_payable": 22410, "claim_date": "2024-08-23", "policy_start_date": "2024-01-16", "policy_end_date": "2025-01-15"}
- Failing or review rules: R02 fail, R06 fail, R07 review
- Missing: Discharge Summary; pending: Policy Copy; rejected: none
- Consistency flags: C1; needs human review: True
- Must mention: Cancelled, Discharge Summary
- [ ] Signed off (name, date):

## CA005 CLM300012: Schedule waiting period not met (R03 fail)

- Question: "Assess claim CLM300012 for approval."
- Facts: {"product_name": "Health Secure Plus", "diagnosis_or_loss_type": "Diabetes Complication", "claim_status": "Partially Approved", "claim_amount": 131115, "approved_amount": 56714, "expected_payable": 131115, "claim_date": "2023-08-14", "policy_start_date": "2023-03-20", "policy_end_date": "2024-03-19"}
- Failing or review rules: R03 fail, R06 fail
- Missing: Claim Form, Diagnostic Report, Hospital Bill, Prescription; pending: none; rejected: none
- Consistency flags: C1; needs human review: True
- Must mention: waiting period, 730, Claim Form, Diagnostic Report
- [ ] Signed off (name, date):

## CA006 CLM300077: Maternity inside its 24-month wait (R04 fail)

- Question: "Analyze claim CLM300077."
- Facts: {"product_name": "Family Care Gold", "diagnosis_or_loss_type": "Maternity", "claim_status": "Under Review", "claim_amount": 16266, "approved_amount": 0, "expected_payable": 12389, "claim_date": "2026-05-13", "policy_start_date": "2024-07-11", "policy_end_date": "2025-07-11"}
- Failing or review rules: R01 fail, R04 fail, R05 review, R06 fail, R07 review
- Missing: Diagnostic Report, Discharge Summary; pending: Claim Form; rejected: none
- Consistency flags: none; needs human review: True
- Must mention: Maternity, 730, Diagnostic Report, Discharge Summary
- [ ] Signed off (name, date):

## CA007 CLM300054: Maternity paid on a product that excludes it (R05 fail + C1)

- Question: "Review claim CLM300054."
- Facts: {"product_name": "Senior Health Shield", "diagnosis_or_loss_type": "Maternity", "claim_status": "Approved", "claim_amount": 37419, "approved_amount": 37419, "expected_payable": 34919, "claim_date": "2023-12-03", "policy_start_date": "2022-05-30", "policy_end_date": "2023-05-30"}
- Failing or review rules: R01 fail, R05 fail, R06 fail, R09 fail, R12 fail
- Missing: Claim Form, Hospital Bill; pending: none; rejected: none
- Consistency flags: C1; needs human review: True
- Must mention: Maternity, Senior Health Shield, not cover, Claim Form, Hospital Bill
- [ ] Signed off (name, date):

## CA008 CLM300050: Rejected required document (R07 fail)

- Question: "Analyze claim CLM300050."
- Facts: {"product_name": "Senior Health Shield", "diagnosis_or_loss_type": "Appendicitis", "claim_status": "Under Review", "claim_amount": 280000, "approved_amount": 0, "expected_payable": 200000, "claim_date": "2026-01-03", "policy_start_date": "2025-02-13", "policy_end_date": "2026-02-13"}
- Failing or review rules: R03 fail, R06 fail, R07 fail, R08 fail, R11 fail, R12 fail
- Missing: Cancelled Cheque, Claim Form, Discharge Summary, Prescription; pending: Hospital Bill; rejected: Diagnostic Report
- Consistency flags: none; needs human review: True
- Must mention: rejected, Diagnostic Report, Cancelled Cheque
- [ ] Signed off (name, date):

## CA009 CLM300009: Escalation by fraud score (R10 fail)

- Question: "Evaluate claim CLM300009."
- Facts: {"product_name": "Senior Health Shield", "diagnosis_or_loss_type": "Kidney Stone", "claim_status": "Approved", "claim_amount": 92014, "approved_amount": 92014, "expected_payable": 82014, "claim_date": "2026-05-11", "policy_start_date": "2025-09-06", "policy_end_date": "2026-09-06"}
- Failing or review rules: R04 fail, R06 fail, R09 fail, R10 fail, R12 fail
- Missing: Claim Form, Discharge Summary, Prescription; pending: none; rejected: none
- Consistency flags: C1; needs human review: True
- Must mention: fraud risk score, manual review queue, Claim Form, Discharge Summary
- [ ] Signed off (name, date):

## CA010 CLM300423: Control: fewest blocker fails in the data

- Question: "Give me a summary of claim CLM300423."
- Facts: {"product_name": "Senior Health Shield", "diagnosis_or_loss_type": "Appendicitis", "claim_status": "Under Review", "claim_amount": 42447, "approved_amount": 0, "expected_payable": 35952, "claim_date": "2023-03-15", "policy_start_date": "2022-07-12", "policy_end_date": "2023-07-12"}
- Failing or review rules: none
- Missing: none; pending: none; rejected: none
- Consistency flags: none; needs human review: False
- Must mention: 
- [ ] Signed off (name, date):
