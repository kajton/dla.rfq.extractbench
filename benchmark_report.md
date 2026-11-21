# RFQ extraction benchmark

- Mode: `regex-only`
- Scoring: Exact field accuracy
- PDFs evaluated: 4
- Ground truth available: yes

| PDF | Method | Exact accuracy | Fields | Flags caught | Latency | Failure modes |
| --- | --- | --- | --- | --- | --- | --- |
| SPE4A614VG092.pdf | regex-only | n/a | 0/0 | 2 (not scored) | 0.68s | ambiguous or misaligned table, missing critical fields |
| clean_digital.pdf | regex-only | 100% | 9/9 | 1/1 | 0.02s | none |
| noisy_layout.pdf | regex-only | 100% | 10/10 | 2/2 | 0.02s | ambiguous or misaligned table |
| packaging_clauses.pdf | regex-only | 100% | 11/11 | 3/3 | 0.02s | none |

## Failure-mode notes

Scanned pages and irregular table layouts are flagged when the PDF diagnostics detect them. No warning does not guarantee that every table was interpreted correctly.
