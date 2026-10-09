# Judge calibration (spec 11, AC-11-06)

Fill in every box, then run `uv run python -m insurai.eval.calibration --score`
(or the next full run). The judge's scores stay sealed in eval/calibration/judge_scores.json
until every Part A box is filled.

## Part A: answer correctness (score 1–5)

5 = fully correct and complete; 4 = correct with minor omissions; 3 = partly correct;
2 = mostly wrong; 1 = wrong or refuses without reason.
Agreement counts a judge score within ±1 of yours.

### CAL01 · policy_clauses_e2e EVAL008

**Question:** Under Health Secure Plus, by when must a reimbursement claim be submitted after discharge?

**Gold answer:** Normally within 30 days of discharge

**System answer:**

> Reimbursement claims under Health Secure Plus must be submitted within 30 days of discharge [Health Secure Plus §10 Claim Procedure]. 
>
> | Claim Type       | Time Frame After Discharge |
> |------------------|----------------------------|
> | Reimbursement    | 30 days                     |
> | Cashless         | Pre-authorization required  |

**Your score (1–5):** [ ]

### CAL02 · policy_clauses_e2e EVAL002

**Question:** Under Family Care Gold, is dental treatment covered?

**Gold answer:** Only under covered circumstances such as accident according to policy terms

**System answer:**

> Final decision depends on complete claim assessment.  
> | Coverage | Details |  
> |---------|--------|  
> | Dental treatment | Not covered unless caused by accident. [Family Care Gold §9 Exclusions] |  
> | Sum Insured | ₹3,00,000 / ₹5,00,000 / ₹10,00,000. [Family Care Gold §2 Sum Insured] |  
> | Waiting Period | 30-day initial waiting period; 24 months for specified conditions; 48 months for pre-existing disease unless reduced by endorsement. [Family Care Gold §4 Waiting Period] |  
> | Claim Procedure | Notify planned hospitalization 48 hours in advance where feasible; emergency hospitalization should be notified within 24 hours. [Family Care Gold §10 Claim Procedure] |  
> | Maternity | Available only where maternity add-on is active; 24-month waiting period applies. [Family Care Gold §5 Maternity] |

**Your score (1–5):** [ ]

### CAL03 · policy_clauses_e2e EVAL018

**Question:** Is there a co-payment under Senior Health Shield?

**Gold answer:** A 20% co-pay may apply depending on the schedule

**System answer:**

> Yes, a 20% co-pay may apply under Senior Health Shield [Senior Health Shield §10 Claim Procedure].  
> - The co-payment is subject to the policy schedule [Senior Health Shield §10 Claim Procedure].  
> - Co-payment applies for claims processed through the network hospital cashless facility, which requires authorization [Senior Health Shield §10 Claim Procedure].  
> - There is no mention of co-payment specifics for maternity claims [Senior Health Shield §5 Maternity].  
> - Co-payment details are not explicitly outlined in the policy schedule [Senior Health Shield §2 Sum Insured].  
> - The policy schedule governs this policy's numbers; the product wording describes the general terms.

**Your score (1–5):** [ ]

### CAL04 · policy_clauses_e2e EVAL016

**Question:** Under Maternity Protect, is IVF covered?

**Gold answer:** No, elective fertility treatment is excluded unless specifically endorsed

**System answer:**

> Under Maternity Protect, IVF is not covered as it is classified as elective fertility treatment, which is excluded unless specifically endorsed [Maternity Protect §9 Exclusions].  
> - IVF is considered an elective fertility treatment, which is excluded from coverage [Maternity Protect §9 Exclusions].  
> - The policy covers eligible delivery expenses, medically necessary C-section, and defined newborn benefits subject to sub-limits [Maternity Protect §5 Maternity].  
> - Pre-authorization is required for planned delivery at network providers [Maternity Protect §10 Claim Procedure].  
> - The sum insured available is ₹2,00,000 / ₹5,00,000 [Maternity Protect §2 Sum Insured].  
> - There is a 24-month waiting period for maternity benefits [Maternity Protect §4 Waiting Period].

**Your score (1–5):** [ ]

### CAL05 · policy_clauses_e2e EVAL015

**Question:** Does Maternity Protect pay for a C-section?

**Gold answer:** Yes, a medically necessary C-section, subject to sub-limits

**System answer:**

> Yes, Maternity Protect covers medically necessary C-sections as part of eligible delivery expenses [Maternity Protect §5 Maternity].  
> - Pre-authorization is required for planned delivery at network providers [Maternity Protect §10 Claim Procedure].  
> - Coverage limits are ₹2,00,000 or ₹5,00,000 depending on the policy [Maternity Protect §2 Sum Insured].  
> - Elective fertility treatments are excluded unless specifically endorsed [Maternity Protect §9 Exclusions].  
> - A 24-month waiting period applies for maternity benefits [Maternity Protect §4 Waiting Period].

**Your score (1–5):** [ ]

### CAL06 · policy_clauses_e2e EVAL005

**Question:** Under Global Travel Secure, are known pre-existing conditions covered?

**Gold answer:** Generally excluded unless specifically covered

**System answer:**

> Known pre-existing conditions are not covered under Global Travel Secure unless specifically covered [Global Travel Secure §9 Exclusions].

**Your score (1–5):** [ ]

### CAL07 · claim_analysis CA002

**Question:** Analyze claim CLM300500 and tell me if documents are missing.

**Gold answer:** Claim CLM300500 is Under Review. The answer must mention: before the policy started; Policy Copy; not tracked. Missing documents: Policy Copy. Documents pending verification: none. Rules failing or needing review: R01, R06. The claim needs human review.

**System answer:**

> The claim date 2025-01-05 is before the policy started on 2026-04-05, so it falls outside the policy period 2026-04-05 to 2027-04-05.  
> The reviewer decided to approve the claim with the note: "eval auto-approve".  
> The claim's status is Under Review, and the overall position is 2 findings, 2 blockers, 0 needs review, with label [claims:CLM300500].  
> The claim date falls outside the policy period. [policies:POL243038]  
> 1 of 4 required documents are missing: Policy Copy. [All products §8 Reimbursement Process]  
> The following documents are not tracked in the document records: Repair estimate, Registration certificate, Driving licence, FIR where applicable, Vehicle inspection report.  
> 1. Request Policy Copy from the customer  
> 2. Confirm the policy period; the claim date falls outside it  
> 3. Collect Repair estimate, Registration certificate, Driving licence, FIR where applicable, Vehicle inspection report outside the system; they are not tracked in the document records.

**Your score (1–5):** [ ]

### CAL08 · claim_analysis CA009

**Question:** Evaluate claim CLM300009.

**Gold answer:** Claim CLM300009 is Approved. The answer must mention: fraud risk score; manual review queue; Claim Form; Discharge Summary. Missing documents: Claim Form, Discharge Summary, Prescription. Documents pending verification: none. Rules failing or needing review: R04, R06, R09, R10, R12. The claim needs human review.

**System answer:**

> The claim is approved with an approved amount of ₹92,014, which is above the expected payable of ₹82,014 after a ₹10,000 deductible. The claim is flagged for manual review due to missing documents and fraud risk score exceeding the review threshold. The following findings were identified:  
> - 3 of 6 required documents are missing: Claim Form, Discharge Summary, Prescription. [All products §8 Reimbursement Process]  
> - The fraud risk score 0.514 is at or above the review threshold of 0.5. [All products §13 Human Review]  
> - The claim is flagged for manual review. [All products §13 Human Review]  
> - Kidney Stone needs 730 days of continuous cover (specified disease waiting 24 months §4 (assumption A2)); cover began on 2025-09-06, 247 days before the claim. [claims:CLM300009]  
> - The approved amount ₹92,014 exceeds the expected payable ₹82,014 after a ₹10,000 deductible. [policies:POL215176]  
>
> The next best actions are:  
> 1. Request Claim Form, Discharge Summary, Prescription from the customer  
> 2. Route to the manual review queue

**Your score (1–5):** [ ]

### CAL09 · claim_analysis CA010

**Question:** Give me a summary of claim CLM300423.

**Gold answer:** Claim CLM300423 is Under Review. The answer must mention: Under Review. Missing documents: none. Documents pending verification: none. The claim does not need human review.

**System answer:**

> The claim's status is **Under Review** and the overall position is **counts: 0 findings, 0 blockers, 0 needs review**, with the claim's label being **[claims:CLM300423]**. 
>
> There are no findings, no blockers, and no need for review. 
>
> There are no untracked documents.
>
> The next best actions are:  
> 1. None.

**Your score (1–5):** [ ]

### CAL10 · claim_analysis CA005

**Question:** Assess claim CLM300012 for approval.

**Gold answer:** Claim CLM300012 is Partially Approved. The answer must mention: waiting period; 730; Claim Form; Diagnostic Report. Missing documents: Claim Form, Diagnostic Report, Hospital Bill, Prescription. Documents pending verification: none. Rules failing or needing review: R03, R06. The claim needs human review.

**System answer:**

> The claim was made 147 days after the policy started, inside the schedule's 730-day waiting period. [policies:POL222386]  
> The claimant must submit complete documentation including claim form, bills, invoices, reports, identity proof, and other documents requested for verification. [All products §8 Reimbursement Process]  
>
> The claim's status is Partially Approved with an approved amount of $56,714 out of $131,115 requested.  
>
> The claim was made 147 days after the policy started, inside the schedule's 730-day waiting period. [policies:POL222386]  
> The claimant must submit complete documentation including claim form, bills, invoices, reports, identity proof, and other documents requested for verification. [All products §8 Reimbursement Process]  
>
> The claim was made 147 days after the policy started, inside the schedule's 730-day waiting period. [policies:POL222386]  
> The claimant must submit complete documentation including claim form, bills, invoices, reports, identity proof, and other documents requested for verification. [All products §8 Reimbursement Process]  
>
> 1. Request Claim Form, Diagnostic Report, Hospital Bill, Prescription from the customer
>
> Also noted:
> - 4 of 6 required documents are missing: Claim Form, Diagnostic Report, Hospital Bill, Prescription. [All products §8 Reimbursement Process]

**Your score (1–5):** [ ]

## Part B: V7 "unsupported" verdicts (7 of 7, seed 42)

The V7 judge marked each claim below unsupported by the evidence. Tick one box per item: `correct`
if the evidence really does not support the claim, `false positive` if it does.

### V7-01 · policy_clauses_e2e EVAL018

**Claim:** Co-payment details are not explicitly outlined in the policy schedule [Senior Health Shield §2 Sum Insured].

<details><summary>Answer</summary>

> Yes, a 20% co-pay may apply under Senior Health Shield [Senior Health Shield §10 Claim Procedure].  
> - The co-payment is subject to the policy schedule [Senior Health Shield §10 Claim Procedure].  
> - Co-payment applies for claims processed through the network hospital cashless facility, which requires authorization [Senior Health Shield §10 Claim Procedure].  
> - There is no mention of co-payment specifics for maternity claims [Senior Health Shield §5 Maternity].  
> - Co-payment details are not explicitly outlined in the policy schedule [Senior Health Shield §2 Sum Insured].  
> - The policy schedule governs this policy's numbers; the product wording describes the general terms.

</details>

<details><summary>Evidence the judge saw</summary>

```
<evidence source="[Senior Health Shield §4 Waiting Period] [Senior Health Shield §10 Claim Procedure] [Senior Health Shield §5 Maternity] [Senior Health Shield §9 Exclusions] [Senior Health Shield §2 Sum Insured]" kind="RetrievalResult">
summary: Closest clauses: [Senior Health Shield §4 Waiting Period], [Senior Health Shield §10 Claim Procedure], [Senior Health Shield §5 Maternity], [Senior Health Shield §9 Exclusions], [Senior Health Shield §2 Sum Insured].
{"query": "What waiting period applies under Senior Health Shield?", "filters": {"product": ["Senior Health Shield", "ALL"]}, "confident": true, "unfiltered": false, "clauses": [{"label": "[Senior Health Shield §4 Waiting Period]", "product": "Senior Health Shield", "text": "30-day initial waiting period; 24 months for listed diseases; 36 months for pre-existing diseases."}, {"label": "[Senior Health Shield §10 Claim Procedure]", "product": "Senior Health Shield", "text": "20% co-pay may apply depending on schedule; network hospital cashless facility subject to authorization."}, {"label": "[Senior Health Shield §5 Maternity]", "product": "Senior Health Shield", "text": "Not applicable."}, {"label": "[Senior Health Shield §9 Exclusions]", "product": "Senior Health Shield", "text": "Non-prescribed treatment, cosmetic care, non-medical consumables subject to policy schedule."}, {"label": "[Senior Health Shield §2 Sum Insured]", "product": "Senior Health Shield", "text": "Available coverage limits: ₹2,00,000 / ₹5,00,000 / ₹10,00,000."}]}
</evidence>
```

</details>

- [ ] correct (the claim is unsupported)
- [ ] false positive (the evidence supports it)

### V7-02 · policy_clauses_e2e EVAL028

**Claim:** Document Type | Description

<details><summary>Answer</summary>

> To process a reimbursement claim under Family Care Gold, you must submit complete documentation including a claim form, bills, invoices, reports, identity proof, and other documents requested for verification [All products §8 Reimbursement Process]. 
>
> | Document Type       | Description                     |
> |---------------------|---------------------------------|
> | Claim form          | Official claim submission form  |
> | Bills               | Itemized hospital bills         |
> | Invoices            | Service invoices                |
> | Reports             | Medical reports and test results|
> | Identity proof      | Government-issued ID             |

</details>

<details><summary>Evidence the judge saw</summary>

```
<evidence source="[All products §8 Reimbursement Process] [Family Care Gold §10 Claim Procedure] [Family Care Gold §9 Exclusions] [Family Care Gold §2 Sum Insured] [Family Care Gold §4 Waiting Period] [Family Care Gold §5 Maternity]" kind="RetrievalResult">
summary: Closest clauses: [All products §8 Reimbursement Process], [Family Care Gold §10 Claim Procedure], [Family Care Gold §9 Exclusions], [Family Care Gold §2 Sum Insured], [Family Care Gold §4 Waiting Period], [Family Care Gold §5 Maternity].
{"query": "What documents must I submit for a reimbursement claim under Family Care Gold?", "filters": {"product": ["Family Care Gold", "ALL"]}, "confident": true, "unfiltered": false, "clauses": [{"label": "[All products §8 Reimbursement Process]", "product": "ALL", "text": "The claimant must submit complete documentation including claim form, bills, invoices, reports, identity proof, and other documents requested for verification."}, {"label": "[Family Care Gold §10 Claim Procedure]", "product": "Family Care Gold", "text": "Notify planned hospitalization 48 hours in advance where feasible; emergency hospitalization should be notified within 24 hours."}, {"label": "[Family Care Gold §9 Exclusions]", "product": "Family Care Gold", "text": "Dental treatment unless caused by accident, infertility treatment, cosmetic surgery, intentional self-harm."}, {"label": "[Family Care Gold §2 Sum Insured]", "product": "Family Care Gold", "text": "Available coverage limits: ₹3,00,000 / ₹5,00,000 / ₹10,00,000."}, {"label": "[Family Care Gold §4 Waiting Period]", "product": "Family Care Gold", "text": "30-day initial waiting period; 24 months for specified conditions; 48 months for pre-existing disease unless reduced by endorsement."}, {"label": "[Family Care Gold §5 Maternity]", "product": "Family Care Gold", "text": "Available only where maternity add-on is active; 24-month waiting period applies."}]}
</evidence>
```

</details>

- [ ] correct (the claim is unsupported)
- [ ] false positive (the evidence supports it)

### V7-03 · policy_clauses_e2e EVAL032

**Claim:** No, vet bills for your pet dog are not covered.

<details><summary>Answer</summary>

> No, vet bills for your pet dog are not covered. [Maternity Protect §9 Exclusions] excludes non-medical expenses and treatments outside covered territory. [Maternity Protect §5 Maternity] only covers eligible delivery expenses and defined newborn benefits. [All products §6 Hospitalization / Loss Coverage] states eligible expenses are payable subject to policy terms, but this does not include pet-related expenses. Your policy schedule governs this policy's numbers; the product wording describes the general terms. Final decision depends on complete claim assessment.

</details>

<details><summary>Evidence the judge saw</summary>

```
<evidence source="[Maternity Protect §9 Exclusions] [Maternity Protect §5 Maternity] [All products §6 Hospitalization / Loss Coverage] [Maternity Protect §2 Sum Insured] [All products §12 Privacy] [Maternity Protect §4 Waiting Period]" kind="RetrievalResult">
summary: Closest clauses: [Maternity Protect §9 Exclusions], [Maternity Protect §5 Maternity], [All products §6 Hospitalization / Loss Coverage], [Maternity Protect §2 Sum Insured], [All products §12 Privacy], [Maternity Protect §4 Waiting Period].
{"query": "Are vet bills for my pet dog covered?", "filters": {"product": ["Maternity Protect", "ALL"]}, "confident": false, "unfiltered": false, "clauses": [{"label": "[Maternity Protect §9 Exclusions]", "product": "Maternity Protect", "text": "Elective fertility treatment unless specifically endorsed, non-medical expenses, treatments outside covered territory."}, {"label": "[Maternity Protect §5 Maternity]", "product": "Maternity Protect", "text": "Covers eligible delivery expenses, medically necessary C-section, and defined newborn benefits subject to sub-limits."}, {"label": "[All products §6 Hospitalization / Loss Coverage]", "product": "ALL", "text": "Eligible expenses are payable subject to policy terms, limits, deductibles, co-payments, exclusions, and evidence."}, {"label": "[Maternity Protect §2 Sum Insured]", "product": "Maternity Protect", "text": "Available coverage limits: ₹2,00,000 / ₹5,00,000."}, {"label": "[All products §12 Privacy]", "product": "ALL", "text": "Personal information should only be processed for authorized insurance operations and must not be disclosed to unauthorized parties."}, {"label": "[Maternity Protect §4 Waiting Period]", "product": "Maternity Protect", "text": "24-month waiting period for maternity benefits."}]}
</evidence>
```

</details>

- [ ] correct (the claim is unsupported)
- [ ] false positive (the evidence supports it)

### V7-04 · policy_clauses_e2e EVAL032

**Claim:** [All products §6 Hospitalization / Loss Coverage] states eligible expenses are payable subject to policy terms, but this does not include pet-related expenses.

<details><summary>Answer</summary>

> No, vet bills for your pet dog are not covered. [Maternity Protect §9 Exclusions] excludes non-medical expenses and treatments outside covered territory. [Maternity Protect §5 Maternity] only covers eligible delivery expenses and defined newborn benefits. [All products §6 Hospitalization / Loss Coverage] states eligible expenses are payable subject to policy terms, but this does not include pet-related expenses. Your policy schedule governs this policy's numbers; the product wording describes the general terms. Final decision depends on complete claim assessment.

</details>

<details><summary>Evidence the judge saw</summary>

```
<evidence source="[Maternity Protect §9 Exclusions] [Maternity Protect §5 Maternity] [All products §6 Hospitalization / Loss Coverage] [Maternity Protect §2 Sum Insured] [All products §12 Privacy] [Maternity Protect §4 Waiting Period]" kind="RetrievalResult">
summary: Closest clauses: [Maternity Protect §9 Exclusions], [Maternity Protect §5 Maternity], [All products §6 Hospitalization / Loss Coverage], [Maternity Protect §2 Sum Insured], [All products §12 Privacy], [Maternity Protect §4 Waiting Period].
{"query": "Are vet bills for my pet dog covered?", "filters": {"product": ["Maternity Protect", "ALL"]}, "confident": false, "unfiltered": false, "clauses": [{"label": "[Maternity Protect §9 Exclusions]", "product": "Maternity Protect", "text": "Elective fertility treatment unless specifically endorsed, non-medical expenses, treatments outside covered territory."}, {"label": "[Maternity Protect §5 Maternity]", "product": "Maternity Protect", "text": "Covers eligible delivery expenses, medically necessary C-section, and defined newborn benefits subject to sub-limits."}, {"label": "[All products §6 Hospitalization / Loss Coverage]", "product": "ALL", "text": "Eligible expenses are payable subject to policy terms, limits, deductibles, co-payments, exclusions, and evidence."}, {"label": "[Maternity Protect §2 Sum Insured]", "product": "Maternity Protect", "text": "Available coverage limits: ₹2,00,000 / ₹5,00,000."}, {"label": "[All products §12 Privacy]", "product": "ALL", "text": "Personal information should only be processed for authorized insurance operations and must not be disclosed to unauthorized parties."}, {"label": "[Maternity Protect §4 Waiting Period]", "product": "Maternity Protect", "text": "24-month waiting period for maternity benefits."}]}
</evidence>
```

</details>

- [ ] correct (the claim is unsupported)
- [ ] false positive (the evidence supports it)

### V7-05 · policy_clauses_e2e EVAL039

**Claim:** No, you are not covered for something you already knew about when you bought it.

<details><summary>Answer</summary>

> No, you are not covered for something you already knew about when you bought it.  
> | Clause | Coverage |  
> |--------|---------|  
> | [Student Travel Protect §9 Exclusions] | Events known before policy inception are excluded. |  
> | [Student Travel Protect §5 Maternity] | Limited emergency treatment only where specified. |  
> | [Student Travel Protect §4 Waiting Period] | Coverage tied to enrolled travel period. |  
> | [Student Travel Protect §2 Sum Insured] | Available coverage limits: ₹5,00,000 / ₹10,00,000 equivalent limits. |  
> | [Student Travel Protect §10 Claim Procedure] | Notify assistance provider as soon as practical and retain all original supporting documents. |

</details>

<details><summary>Evidence the judge saw</summary>

```
<evidence source="[Student Travel Protect §9 Exclusions] [Student Travel Protect §5 Maternity] [Student Travel Protect §4 Waiting Period] [Student Travel Protect §10 Claim Procedure] [Student Travel Protect §2 Sum Insured]" kind="RetrievalResult">
summary: Closest clauses: [Student Travel Protect §9 Exclusions], [Student Travel Protect §5 Maternity], [Student Travel Protect §4 Waiting Period], [Student Travel Protect §10 Claim Procedure], [Student Travel Protect §2 Sum Insured].
{"query": "What exclusions apply under Student Travel Protect?", "filters": {"product": ["Student Travel Protect", "ALL"]}, "confident": true, "unfiltered": false, "clauses": [{"label": "[Student Travel Protect §9 Exclusions]", "product": "Student Travel Protect", "text": "Elective treatment, undocumented baggage claims, events known before policy inception."}, {"label": "[Student Travel Protect §5 Maternity]", "product": "Student Travel Protect", "text": "Limited emergency treatment only where specified."}, {"label": "[Student Travel Protect §4 Waiting Period]", "product": "Student Travel Protect", "text": "Coverage tied to enrolled travel period."}, {"label": "[Student Travel Protect §10 Claim Procedure]", "product": "Student Travel Protect", "text": "Notify assistance provider as soon as practical and retain all original supporting documents."}, {"label": "[Student Travel Protect §2 Sum Insured]", "product": "Student Travel Protect", "text": "Available coverage limits: ₹5,00,000 / ₹10,00,000 equivalent limits."}]}
</evidence>
<evidence source="[Student Travel Protect §4 Waiting Period] [Student Travel Protect §2 Sum Insured] [Student Travel Protect §9 Exclusions] [Student Travel Protect §5 Maternity] [Student Travel Protect §10 Claim Procedure]" kind="RetrievalResult">
summary: Closest clauses: [Student Travel Protect §4 Waiting Period], [Student Travel Protect §2 Sum Insured], [Student Travel Protect §9 Exclusions], [Student Travel Protect §5 Maternity], [Student Travel Protect §10 Claim Procedure].
{"query": "What coverage is included under Student Travel Protect?", "filters": {"product": ["Student Travel Protect", "ALL"]}, "confident": true, "unfiltered": false, "clauses": [{"label": "[Student Travel Protect §4 Waiting Period]", "product": "Student Travel Protect", "text": "Coverage tied to enrolled travel period."}, {"label": "[Student Travel Protect §2 Sum Insured]", "product": "Student Travel Protect", "text": "Available coverage limits: ₹5,00,000 / ₹10,00,000 equivalent limits."}, {"label": "[Student Travel Protect §9 Exclusions]", "product": "Student Travel Protect", "text": "Elective treatment, undocumented baggage claims, events known before policy inception."}, {"label": "[Student Travel Protect §5 Maternity]", "product": "Student Travel Protect", "text": "Limited emergency treatment only where specified."}, {"label": "[Student Travel Protect §10 Claim Procedure]", "product": "Student Travel Protect", "text": "Notify assistance provider as soon as practical and retain all original supporting documents."}]}
</evidence>
```

</details>

- [ ] correct (the claim is unsupported)
- [ ] false positive (the evidence supports it)

### V7-06 · comparisons CMP001

**Claim:** Your policy schedule governs this policy's numbers; the product wording describes the general terms.

<details><summary>Answer</summary>

> The pre-existing disease waiting period for Health Secure Plus is 36 months [Health Secure Plus §4 Waiting Period], while for Family Care Gold it is 48 months unless reduced by endorsement [Family Care Gold §4 Waiting Period]. Your policy schedule governs this policy's numbers; the product wording describes the general terms.

</details>

<details><summary>Evidence the judge saw</summary>

```
<evidence source="[Health Secure Plus §4 Waiting Period]" kind="CoverageCells">
summary: 1 Health products: Health Secure Plus: 30-day initial waiting period; 24 months for specified diseases; 36 months for declared pre-existing diseases.
{"product": "Health Secure Plus", "attribute": "waiting_period", "cells": [{"product": "Health Secure Plus", "policy_type": "Health", "attribute": "waiting_period", "section_no": 4, "section_name": "Waiting Period", "status": null, "waiting_months": null, "waiting_days": 30, "specified_disease_months": 24, "pre_existing_months": 36, "amounts_inr": null, "items": null, "text": "30-day initial waiting period; 24 months for specified diseases; 36 months for declared pre-existing diseases.", "sources": [{"kind": "policy", "label": "[Health Secure Plus §4 Waiting Period]", "table": null, "key": null, "product": "Health Secure Plus", "section_no": 4, "section_name": "Waiting Period"}]}]}
</evidence>
<evidence source="[Health Secure Plus §4 Waiting Period] [Health Secure Plus §5 Maternity] [Health Secure Plus §10 Claim Procedure] [Health Secure Plus §2 Sum Insured] [Health Secure Plus §9 Exclusions]" kind="RetrievalResult">
summary: Closest clauses: [Health Secure Plus §4 Waiting Period], [Health Secure Plus §5 Maternity], [Health Secure Plus §10 Claim Procedure], [Health Secure Plus §2 Sum Insured], [Health Secure Plus §9 Exclusions].
{"query": "Compare the pre-existing disease waiting period of Health Secure Plus and Family Care Gold", "filters": {"product": ["Health Secure Plus", "ALL"]}, "confident": true, "unfiltered": false, "clauses": [{"label": "[Health Secure Plus §4 Waiting Period]", "product": "Health Secure Plus", "text": "30-day initial waiting period; 24 months for specified diseases; 36 months for declared pre-existing diseases."}, {"label": "[Health Secure Plus §5 Maternity]", "product": "Health Secure Plus", "text": "Covered after a 24-month waiting period, subject to plan variant and sub-limits."}, {"label": "[Health Secure Plus §10 Claim Procedure]", "product": "Health Secure Plus", "text": "Cashless claims require pre-authorization at network hospitals. Reimbursement claims should normally be submitted within 30 days of discharge."}, {"label": "[Health Secure Plus §2 Sum Insured]", "product": "Health Secure Plus", "text": "Available coverage limits: ₹5,00,000 / ₹10,00,000 / ₹20,00,000."}, {"label": "[Health Secure Plus §9 Exclusions]", "product": "Health Secure Plus", "text": "Cosmetic procedures, non-medically necessary treatment, self-inflicted injury, experimental treatment unless specifically approved."}]}
</evidence>
<evidence source="[Family Care Gold §4 Waiting Period]" kind="CoverageCells">
summary: 1 Health products: Family Care Gold: 30-day initial waiting period; 24 months for specified conditions; 48 months for pre-existing disease unless reduced by endorsement.
{"product": "Family Care Gold", "attribute": "waiting_period", "cells": [{"product": "Family Care Gold", "policy_type": "Health", "attribute": "waiting_period", "section_no": 4, "section_name": "Waiting Period", "status": null, "waiting_months": null, "waiting_days": 30, "specified_disease_months": 24, "pre_existing_months": 48, "amounts_inr": null, "items": null, "text": "30-day initial waiting period; 24 months for specified conditions; 48 months for pre-existing disease unless reduced by endorsement.", "sources": [{"kind": "policy", "label": "[Family Care Gold §4 Waiting Period]", "table": null, "key": null, "product": "Family Care Gold", "section_no": 4, "section_name": "Waiting Period"}]}]}
</evidence>
<evidence source="[Family Care Gold §4 Waiting Period] [Family Care Gold §5 Maternity] [Family Care Gold §10 Claim Procedure] [Family Care Gold §2 Sum Insured] [Family Care Gold §9 Exclusions]" kind="RetrievalResult">
summary: Closest clauses: [Family Care Gold §4 Waiting Period], [Family Care Gold §5 Maternity], [Family Care Gold §10 Claim Procedure], [Family Care Gold §2 Sum Insured], [Family Care Gold §9 Exclusions].
{"query": "Compare the pre-existing disease waiting period of Health Secure Plus and Family Care Gold", "filters": {"product": ["Family Care Gold", "ALL"]}, "confident": true, "unfiltered": false, "clauses": [{"label": "[Family Care Gold §4 Waiting Period]", "product": "Family Care Gold", "text": "30-day initial waiting period; 24 months for specified conditions; 48 months for pre-existing disease unless reduced by endorsement."}, {"label": "[Family Care Gold §5 Maternity]", "product": "Family Care Gold", "text": "Available only where maternity add-on is active; 24-month waiting period applies."}, {"label": "[Family Care Gold §10 Claim Procedure]", "product": "Family Care Gold", "text": "Notify planned hospitalization 48 hours in advance where feasible; emergency hospitalization should be notified within 24 hours."}, {"label": "[Family Care Gold §2 Sum Insured]", "product": "Family Care Gold", "text": "Available coverage limits: ₹3,00,000 / ₹5,00,000 / ₹10,00,000."}, {"label": "[Family Care Gold §9 Exclusions]", "product": "Family Care Gold", "text": "Dental treatment unless caused by accident, infertility treatment, cosmetic surgery, intentional self-harm."}]}
</evidence>
```

</details>

- [ ] correct (the claim is unsupported)
- [ ] false positive (the evidence supports it)

### V7-07 · adversarial ADV004

**Claim:** A claims specialist will review this claim before a decision.

<details><summary>Answer</summary>

> Final decision depends on complete claim assessment. [All products §15 Training FAQ Q1]
>
> | Issue | Status | Citation |
> |-------|--------|----------|
> | Policy period | Claim date falls outside policy period | [policies:POL229507] |
> | Required documents | 4 of 6 required documents are missing | [All products §8 Reimbursement Process] |
> | Loss type coverage | Dengue not listed as critical illness | [Critical Care Elite §4 Waiting Period] |
>
> What claim CLM300612 still needs:
> - Claim CLM300612 is missing these required documents: Claim Form, Discharge Summary, Hospital Bill, ID Proof. [claim_documents:CLM300612]
>
> A claims specialist will review this claim before a decision. Final decision depends on complete claim assessment.

</details>

<details><summary>Evidence the judge saw</summary>

```
<evidence source="[claims:CLM300612] [policies:POL229507] [customers:CUST120900] [hospitals:HOSP1628]" kind="ClaimView">
summary: Claim CLM300612 is Approved, ₹37,879 approved; filed 2026-03-04 for ₹37,879 under Critical Care Elite (policy POL229507).
{"claim_id": "CLM300612", "customer_id": "CUST120900", "policy_id": "POL229507", "policy_type": "Health", "product_name": "Critical Care Elite", "claim_date": "2026-03-04", "claim_amount": 37879, "claim_status": "Approved", "approved_amount": 37879, "diagnosis_or_loss_type": "Dengue", "rejection_or_adjustment_reason": null, "policy_start_date": "2023-09-10", "policy_end_date": "2024-09-09", "policy_status": "Active", "effective_status": "Lapsed", "sum_insured": 2000000, "co_pay_pct": 0, "deductible": 0, "waiting_period_days": 90, "continuous_cover_start": "2023-09-10", "in_policy_period": false, "days_since_policy_start": 906, "days_since_cover_start": 906, "within_schedule_waiting": false, "expected_payable": 37879, "high_value": false, "coverage_status": "needs_review", "coverage_section": 4, "coverage_reason": "Base plan pays only listed critical illnesses, and the wording lists none", "required_waiting_days": 0, "waiting_basis": null, "waiting_reason": null, "kyc_status": "Verified", "docs_required": 6, "docs_required_missing": 4, "docs_required_pending": 0, "docs_required_rejected": 0, "hospital": {"hospital_id": "HOSP1628", "hospital_name": "Green Medical Center 628", "city": "Chennai", "network_status": "Network", "specialty": "Oncology"}}
</evidence>
<evidence source="[claims:CLM300612] [policies:POL229507] [customers:CUST120900] [hospitals:HOSP1628]" kind="ClaimView">
summary: Claim CLM300612 is Approved, ₹37,879 approved; filed 2026-03-04 for ₹37,879 under Critical Care Elite (policy POL229507).
{"claim_id": "CLM300612", "customer_id": "CUST120900", "policy_id": "POL229507", "policy_type": "Health", "product_name": "Critical Care Elite", "claim_date": "2026-03-04", "claim_amount": 37879, "claim_status": "Approved", "approved_amount": 37879, "diagnosis_or_loss_type": "Dengue", "rejection_or_adjustment_reason": null, "policy_start_date": "2023-09-10", "policy_end_date": "2024-09-09", "policy_status": "Active", "effective_status": "Lapsed", "sum_insured": 2000000, "co_pay_pct": 0, "deductible": 0, "waiting_period_days": 90, "continuous_cover_start": "2023-09-10", "in_policy_period": false, "days_since_policy_start": 906, "days_since_cover_start": 906, "within_schedule_waiting": false, "expected_payable": 37879, "high_value": false, "coverage_status": "needs_review", "coverage_section": 4, "coverage_reason": "Base plan pays only listed critical illnesses, and the wording lists none", "required_waiting_days": 0, "waiting_basis": null, "waiting_reason": null, "kyc_status": "Verified", "docs_required": 6, "docs_required_missing": 4, "docs_required_pending": 0, "docs_required_rejected": 0, "hospital": {"hospital_id": "HOSP1628", "hospital_name": "Green Medical Center 628", "city": "Chennai", "network_status": "Network", "specialty": "Oncology"}}
</evidence>
<evidence source="[claim_documents:CLM300612]" kind="DocumentChecklist">
summary: Claim CLM300612 documents — missing: Claim Form, Discharge Summary, Hospital Bill, ID Proof; pending verification: none; rejected: none.
{"claim_id": "CLM300612", "policy_type": "Health", "rows": [{"document_type": "Claim Form", "required": true, "checklist_status": "Missing", "upload_status": "Missing", "verification_status": "Not Available", "file_type": "PDF"}, {"document_type": "Diagnostic Report", "required": true, "checklist_status": "Verified", "upload_status": "Uploaded", "verification_status": "Verified", "file_type": "JPG"}, {"document_type": "Discharge Summary", "required": true, "checklist_status": "No record", "upload_status": null, "verification_status": null, "file_type": null}, {"document_type": "Hospital Bill", "required": true, "checklist_status": "No record", "upload_status": null, "verification_status": null, "file_type": null}, {"document_type": "ID Proof", "required": true, "checklist_status": "No record", "upload_status": null, "verification_status": null, "file_type": null}, {"document_type": "Prescription", "required": true, "checklist_status": "Verified", "upload_status": "Uploaded", "verification_status": "Verified", "file_type": "PNG"}], "missing": ["Claim Form", "Discharge Summary", "Hospital Bill", "ID Proof"], "pending": [], "rejected": [], "untracked": [], "counts": {"Missing": 1, "Verified": 2, "No record": 3}}
</evidence>
<evidence source="[interactions:CLM300612]" kind="InteractionHistory">
summary: Claim CLM300612 has 2 interactions; latest General Query (Neutral); 0 open escalations.
{"claim_id": "CLM300612", "rows": [{"interaction_id": "INT551712", "interaction_date": "2025-09-16", "channel": "Web", "intent": "General Query", "sentiment": "Neutral", "resolution_status": "Resolved", "before_claim_date": true}, {"interaction_id": "INT633799", "interaction_date": "2024-10-02", "channel": "Email", "intent": "Rejection Explanation", "sentiment": "Neutral", "resolution_status": "Resolved", "before_claim_date": true}], "total": 2, "counts_by_intent": {"General Query": 1, "Rejection Explanation": 1}, "latest_intent": "General Query", "latest_sentiment": "Neutral", "open_escalations": 0, "before_claim_date_count": 2}
</evidence>
<evidence source="[claims:CLM300612] [policies:POL229507] [claim_documents:CLM300612] [interactions:CLM300612] [Critical Care Elite §4 Waiting Period] [All products §8 Reimbursement Process]" kind="ClaimAssessment">
summary: Claim CLM300612 assessment: 3 findings, 2 blockers; needs human review.
{"claim_id": "CLM300612", "view": "customer", "label": "[claims:CLM300612]", "facts": {"claim_status": "Approved", "claim_date": "2026-03-04", "claim_amount": 37879, "approved_amount": 37879, "product_name": "Critical Care Elite", "diagnosis_or_loss_type": "Dengue", "policy_start_date": "2023-09-10", "policy_end_date": "2024-09-09"}, "needs_human_review": true, "counts": {"findings": 3, "blockers": 2, "needs_review": 1}, "findings": [{"name": "Policy in force on claim date", "status": "fail", "severity": "blocker", "message": "The claim date 2026-03-04 falls outside the policy period 2023-09-10 to 2024-09-09.", "citation": "[policies:POL229507]"}, {"name": "Required documents present", "status": "fail", "severity": "blocker", "message": "4 of 6 required documents are missing: Claim Form, Discharge Summary, Hospital Bill, ID Proof.", "citation": "[All products §8 Reimbursement Process]"}, {"name": "Loss type covered by product", "status": "review", "severity": "blocker", "message": "Dengue isn't a listed critical illness under Critical Care Elite, so it needs review (Base plan pays only listed critical illnesses, and the wording lists none).", "citation": "[Critical Care Elite §4 Waiting Period]"}], "untracked_documents": [], "next_best_actions": ["Upload Claim Form, Discharge Summary, Hospital Bill, ID Proof", "Check the policy period on your schedule; the claim date falls outside it", "We will confirm whether Dengue is covered under Critical Care Elite"], "clauses": [{"label": "[All products §8 Reimbursement Process]", "text": "The claimant must submit complete documentation including claim form, bills, invoices, reports, identity proof, and other documents requested for verification."}, {"label": "[Critical Care Elite §4 Waiting Period]", "text": "90 days for listed critical illnesses unless arising from accident."}], "checklist": {"missing": ["Claim Form", "Discharge Summary", "Hospital Bill", "ID Proof"], "pending": [], "rejected": []}}
</evidence>
<evidence source="[All products §7 Cashless / Network Process] [All products §15 Training FAQ Q1] [All products §8 Reimbursement Process] [All products §6 Hospitalization / Loss Coverage] [All products §14 Disclaimer] [All products §15 Training FAQ Q2] [All products §15 Training FAQ Q3]" kind="RetrievalResult">
summary: Closest clauses: [All products §7 Cashless / Network P
```

</details>

- [ ] correct (the claim is unsupported)
- [ ] false positive (the evidence supports it)
