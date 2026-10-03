# Raw data (not committed)

Unzip the delivered `insurance_genai_cdataset.zip` here so the layout is:

```
data/raw/
├── customers.csv               50,000 rows
├── policies.csv                75,000
├── claims.csv                 120,000
├── claim_documents.csv        600,010
├── hospitals.csv                1,200
├── customer_interactions.csv  180,000
├── evaluation_questions.csv         5   (header row is "0,1,2,3,4"; spec 11 fixes it on import)
├── README_DATASET.txt
└── policy_documents/          10 .txt wordings
```

Never edit these files (CLAUDE.md rule 7).
