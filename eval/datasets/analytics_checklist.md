# Analytics slice sign-off (spec 02, AC-02-07)

15 items (decided 2026-10-08, 3-day scope; spec 11 says 20). Gold rows below are computed through the
validator and executor as the item's persona, so claims_agent name items show initials. Items stay tagged
`draft` in analytics.jsonl until every box is ticked; then remove the tag.

## ANA001 · supervisor
**Question:** How many claims of each policy type were filed between January and September 2026?

```sql
SELECT policy_type, COUNT(*) AS claims FROM silver.claims WHERE claim_date >= DATE '2026-01-01' AND claim_date < DATE '2026-10-01' GROUP BY 1
```

First rows (3 in total):

| policy_type | claims |
|---|---|
| Travel | 1972 |
| Health | 16242 |
| Motor | 5763 |

- [ ] signed off

## ANA002 · claims_agent
**Question:** What is the average approved amount on partially approved motor claims?

```sql
SELECT ROUND(AVG(approved_amount)) AS avg_approved_amount FROM silver.claims WHERE policy_type = 'Motor' AND claim_status = 'Partially Approved'
```

First rows (1 in total):

| avg_approved_amount |
|---|
| 33817.0 |

- [ ] signed off

## ANA003 · supervisor
**Question:** List the five hospitals with the highest total amount claimed, with that total.

```sql
SELECT h.hospital_name, SUM(c.claim_amount) AS total_claimed FROM silver.claims c JOIN silver.hospitals h ON h.hospital_id = c.hospital_id GROUP BY h.hospital_id, h.hospital_name ORDER BY total_claimed DESC LIMIT 5
```

First rows (5 in total):

| hospital_name | total_claimed |
|---|---|
| Apollo Medical Center 139 | 10339797 |
| Green Health Institute 282 | 10114995 |
| LifeLine Medical Center 130 | 10076580 |
| Metro Hospital 1116 | 10061514 |
| City Clinic 125 | 9956913 |

- [ ] signed off

## ANA004 · claims_agent
**Question:** How many customers sit in each risk segment?

```sql
SELECT risk_segment, COUNT(*) AS customers FROM silver.customers GROUP BY 1
```

First rows (3 in total):

| risk_segment | customers |
|---|---|
| Low | 29957 |
| High | 3971 |
| Medium | 16072 |

- [ ] signed off

## ANA005 · supervisor
**Question:** For each claim status, what is the mean fraud risk score, rounded to two decimals?

```sql
SELECT claim_status, ROUND(AVG(fraud_risk_score), 2) AS avg_fraud_risk_score FROM silver.claims GROUP BY 1
```

First rows (6 in total):

| claim_status | avg_fraud_risk_score |
|---|---|
| Under Review | 0.16 |
| Partially Approved | 0.16 |
| Pending Documents | 0.16 |
| Approved | 0.16 |
| Submitted | 0.16 |

- [ ] signed off

## ANA006 · claims_agent
**Question:** Break down mobile app interactions by sentiment.

```sql
SELECT sentiment, COUNT(*) AS interactions FROM silver.customer_interactions WHERE channel = 'Mobile App' GROUP BY 1
```

First rows (3 in total):

| sentiment | interactions |
|---|---|
| Positive | 9872 |
| Negative | 7201 |
| Neutral | 19041 |

- [ ] signed off

## ANA007 · claims_agent
**Question:** How many lapsed policies are there per line of business?

```sql
SELECT policy_type, COUNT(*) AS lapsed_policies FROM silver.policies WHERE effective_status = 'Lapsed' GROUP BY 1
```

First rows (3 in total):

| policy_type | lapsed_policies |
|---|---|
| Motor | 15150 |
| Health | 42871 |
| Travel | 5086 |

- [ ] signed off

## ANA008 · supervisor
**Question:** What percentage of claims carry a manual review flag in each line of business, to one decimal?

```sql
SELECT policy_type, ROUND(100.0 * AVG(manual_review_flag), 1) AS manual_review_pct FROM silver.claims GROUP BY 1
```

First rows (3 in total):

| policy_type | manual_review_pct |
|---|---|
| Motor | 17.8 |
| Health | 18.0 |
| Travel | 17.2 |

- [ ] signed off

## ANA009 · claims_agent
**Question:** Which document types get rejected most often during verification?

```sql
SELECT document_type, COUNT(*) AS rejected FROM gold.claim_doc_checklist WHERE checklist_status = 'Rejected' GROUP BY 1 ORDER BY rejected DESC
```

First rows (8 in total):

| document_type | rejected |
|---|---|
| Diagnostic Report | 2678 |
| Claim Form | 2677 |
| Cancelled Cheque | 2660 |
| Hospital Bill | 2648 |
| Policy Copy | 2631 |

- [ ] signed off

## ANA010 · supervisor
**Question:** Show the total approved amount per month across 2025.

```sql
SELECT date_trunc('month', claim_date) AS month, SUM(approved_amount) AS total_approved_amount FROM silver.claims WHERE claim_date >= DATE '2025-01-01' AND claim_date < DATE '2026-01-01' GROUP BY 1 ORDER BY 1
```

First rows (12 in total):

| month | total_approved_amount |
|---|---|
| 2025-01-01T00:00:00 | 105359975 |
| 2025-02-01T00:00:00 | 89316683 |
| 2025-03-01T00:00:00 | 108072964 |
| 2025-04-01T00:00:00 | 96852311 |
| 2025-05-01T00:00:00 | 103225289 |

- [ ] signed off

## ANA011 · claims_agent
**Question:** Give me the customer names and amounts for the five biggest claims ever filed.

```sql
SELECT cu.customer_name, c.claim_amount FROM silver.claims c JOIN silver.customers cu ON cu.customer_id = c.customer_id ORDER BY c.claim_amount DESC LIMIT 5
```

First rows (5 in total):

| customer_name | claim_amount |
|---|---|
| P. V. | 1684956 |
| M. M. | 1564818 |
| V. R. | 1552695 |
| R. M. | 1415344 |
| P. K. | 1400000 |

- [ ] signed off

## ANA012 · claims_agent
**Question:** Which customers lodged trip cancellation claims above 5 lakh rupees? Show names and amounts.

```sql
SELECT cu.customer_name, c.claim_amount FROM silver.claims c JOIN silver.customers cu ON cu.customer_id = c.customer_id WHERE c.diagnosis_or_loss_type = 'Trip Cancellation' AND c.claim_amount > 500000
```

First rows (1 in total):

| customer_name | claim_amount |
|---|---|
| N. I. | 547968 |

- [ ] signed off

## ANA013 · supervisor
**Question:** Per product, how many claims were settled even though a blocking rule had failed?

```sql
SELECT product_name, COUNT(*) AS claims FROM gold.rule_results WHERE C1 GROUP BY 1
```

First rows (10 in total):

| product_name | claims |
|---|---|
| Car Shield Plus | 4900 |
| Two Wheeler Secure | 4798 |
| Student Travel Protect | 2423 |
| Maternity Protect | 8099 |
| Senior Health Shield | 8259 |

- [ ] signed off

## ANA014 · supervisor
**Question:** How many claims turned down for insufficient documents actually had a complete file?

```sql
SELECT COUNT(*) AS claims FROM gold.rule_results WHERE C3
```

First rows (1 in total):

| claims |
|---|
| 241 |

- [ ] signed off

## ANA015 · supervisor
**Question:** By line of business, how many settled claims paid out more than the expected payable?

```sql
SELECT c.policy_type, COUNT(*) AS claims FROM gold.rule_results r JOIN silver.claims c ON c.claim_id = r.claim_id WHERE r.claim_status IN ('Approved', 'Partially Approved') AND r.R09 = 'fail' GROUP BY 1
```

First rows (3 in total):

| policy_type | claims |
|---|---|
| Travel | 2969 |
| Health | 23593 |
| Motor | 8562 |

- [ ] signed off
