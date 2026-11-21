# dla-rfq-parser 🎯

Built this over a weekend to see where standard LLMs break on messy US defense RFQs (DLA / SAM.gov solicitations) vs. a hybrid table + regex + structured output pipeline.

No fluff — just extracts hard procurement data (`NSN`, `CAGE`, `MIL-STD`, `ITAR/Berry` flags) and benchmarks extraction accuracy.

### Why this matters
Defense suppliers win on quoting speed, but government PDFs are a nightmare (broken tables, buried packaging specs, random scans). One missed `MIL-STD-2073` or `Berry Amendment` clause kills the margin.

### How it works
1. **Table & Text Extraction:** `pdfplumber` pulls grid layouts first; `pymupdf` acts as fallback and flags low-text-density scanned pages.
2. **Regex Anchors:** Deterministic pre-pass locks in strict military formats (`NSN`, `Solicitation #`, `MIL-STD`) before the LLM touches anything.
3. **Structured Output:** Pydantic schema forces clean JSON with compliance red-flags and confidence notes.
4. **Eval Harness (`benchmark.py`):** Runs `regex-only` vs `hybrid` side-by-side and spits out a markdown report with failure modes.

### Quickstart
```bash
pip install -r requirements.txt
echo "GEMINI_API_KEY=your_key" > .env

python generate_samples.py   # creates synthetic RFQs + ground truth
python benchmark.py          # runs evals & updates benchmark_report.md
```

The hybrid extractor uses Google's `gemini-3.8-flash` model. Set
`GEMINI_API_KEY` in your environment or `.env` file before running it; the
default benchmark mode (`regex-only`) works without a key.

```bash
python benchmark.py --mode hybrid-llm
python benchmark.py --mode compare
python extractor.py path/to/solicitation.pdf --model gemini-3.8-flash