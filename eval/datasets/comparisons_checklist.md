# Comparisons slice sign-off (spec 11)

5 items (3-day scope; spec 11 asks for 10). Gold comes from config/coverage_matrix.yaml (status reviewed);
a unit test checks every matrix value below appears in the gold answer. Correctness is judged (score >= 4).

Changes at sign-off (Ram, 2026-10-09): CMP002 gold_sources gains [Maternity Protect §4 Waiting Period],
where the 24-month waiting period is stated.

## CMP001

**Question:** Compare the pre-existing disease waiting period of Health Secure Plus and Family Care Gold.

**Gold answer:** Health Secure Plus: 36 months for declared pre-existing diseases. Family Care Gold: 48 months for pre-existing disease unless reduced by endorsement.

Matrix values:

- `Health Secure Plus.waiting.pre_existing_months` = 36
- `Family Care Gold.waiting.pre_existing_months` = 48

Wording:

- [Health Secure Plus §4 Waiting Period] 30-day initial waiting period; 24 months for specified diseases; 36 months for declared pre-existing diseases.
- [Family Care Gold §4 Waiting Period] 30-day initial waiting period; 24 months for specified conditions; 48 months for pre-existing disease unless reduced by endorsement.

- [x] signed off (Ram, 2026-10-09)

## CMP002

**Question:** How does maternity cover differ between Maternity Protect and Critical Care Elite?

**Gold answer:** Maternity Protect: covered after a 24 month waiting period (eligible delivery expenses, medically necessary C-section and defined newborn benefits, subject to sub-limits). Critical Care Elite: not covered under the base critical illness plan.

Matrix values:

- `Maternity Protect.maternity.status` = 'covered'
- `Maternity Protect.maternity.waiting_months` = 24
- `Critical Care Elite.maternity.status` = 'not_covered'

Wording:

- [Maternity Protect §5 Maternity] Covers eligible delivery expenses, medically necessary C-section, and defined newborn benefits subject to sub-limits.
- [Critical Care Elite §5 Maternity] Not covered under the base critical illness plan.

- [x] signed off (Ram, 2026-10-09)

## CMP003

**Question:** Is drunk driving excluded under both Two Wheeler Secure and Motor Protect Comprehensive?

**Gold answer:** Yes, under both. Two Wheeler Secure excludes Drunk driving; Motor Protect Comprehensive excludes Intoxication.

Matrix values:

- `Two Wheeler Secure.exclusions.2` = 'Drunk driving'
- `Motor Protect Comprehensive.exclusions.1` = 'Intoxication'

Wording:

- [Two Wheeler Secure §9 Exclusions] Wear and tear, mechanical/electrical breakdown, drunk driving, illegal use.
- [Motor Protect Comprehensive §9 Exclusions] Driving without valid license, intoxication, consequential loss, mechanical breakdown not caused by insured peril.

- [x] signed off (Ram, 2026-10-09)

## CMP004

**Question:** Compare the claim procedure of Car Shield Plus with Two Wheeler Secure.

**Gold answer:** Car Shield Plus: Cashless repair available only at empanelled garages subject to authorization. Two Wheeler Secure: Vehicle inspection may be required before repair approval.

Matrix values:

- `Car Shield Plus.claim_procedure` = 'Cashless repair available only at empanelled garages subject to authorization.'
- `Two Wheeler Secure.claim_procedure` = 'Vehicle inspection may be required before repair approval.'

Wording:

- [Car Shield Plus §10 Claim Procedure] Cashless repair available only at empanelled garages subject to authorization.
- [Two Wheeler Secure §10 Claim Procedure] Vehicle inspection may be required before repair approval.

- [x] signed off (Ram, 2026-10-09)

## CMP005

**Question:** Which cover amounts do Senior Health Shield and Global Travel Secure offer, side by side?

**Gold answer:** Senior Health Shield: ₹2,00,000, ₹5,00,000 or ₹10,00,000. Global Travel Secure: ₹5,00,000 or ₹10,00,000 equivalent limits.

Matrix values:

- `Senior Health Shield.sum_insured_options_inr` = [200000, 500000, 1000000]
- `Global Travel Secure.sum_insured_options_inr` = [500000, 1000000]

Wording:

- [Senior Health Shield §2 Sum Insured] Available coverage limits: ₹2,00,000 / ₹5,00,000 / ₹10,00,000.
- [Global Travel Secure §2 Sum Insured] Available coverage limits: ₹5,00,000 / ₹10,00,000 equivalent limits.

- [x] signed off (Ram, 2026-10-09)
