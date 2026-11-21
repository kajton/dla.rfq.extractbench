"""Compare RFQ extraction results with optional ground-truth JSON files."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from extractor import DEFAULT_MODEL, extract_pdf
from schema import RFQExtraction

SAMPLE_DIR = Path("sample_rfqs")
GROUND_TRUTH_DIR = Path("ground_truth")
REPORT_PATH = Path("benchmark_report.md")
SCALAR_FIELDS = (
    "solicitation_number",
    "nsn",
    "cage_code",
    "part_number",
    "quantity",
    "unit_of_issue",
    "delivery_days_aro",
    "mil_std_packaging",
)


@dataclass
class BenchmarkResult:
    file_name: str
    method: str
    extraction: RFQExtraction
    latency: float
    correct_fields: int
    expected_fields: int
    flags_caught: int
    expected_flags: int
    failure_modes: list[str]
    error: str | None = None


def _normalize(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    return value


def _score(
    extraction: RFQExtraction, reference: RFQExtraction
) -> tuple[int, int, int, int]:
    correct = 0
    expected = 0

    for field in SCALAR_FIELDS:
        reference_value = getattr(reference, field)
        if reference_value is None:
            continue
        expected += 1
        if _normalize(getattr(extraction, field)) == _normalize(reference_value):
            correct += 1

    reference_flags = {flag.casefold() for flag in reference.compliance_flags}
    extracted_flags = {flag.casefold() for flag in extraction.compliance_flags}
    flags_caught = len(reference_flags & extracted_flags)
    expected += len(reference_flags)
    correct += flags_caught

    return correct, expected, flags_caught, len(reference_flags)


def _failure_modes(
    notes: str, warnings: list[str], error: str | None = None
) -> list[str]:
    messages = [notes, *warnings]
    text = " ".join(messages).casefold()
    failures = []

    if error:
        failures.append(f"extraction error: {error}")
    if "scan" in text:
        failures.append("scanned/low-text page")
    if "table" in text:
        failures.append("ambiguous or misaligned table")
    if "missing critical" in text:
        failures.append("missing critical fields")

    return failures


def _format_result(result: BenchmarkResult, has_truth: bool) -> list[str]:
    failures = ", ".join(result.failure_modes) or "none"
    latency = f"{result.latency:.2f}"

    if not has_truth:
        values = result.extraction.model_dump()
        populated = sum(values[field] is not None for field in SCALAR_FIELDS)
        return [
            result.file_name,
            result.method,
            f"{populated}/{len(SCALAR_FIELDS)}",
            str(len(result.extraction.compliance_flags)),
            f"{latency}s",
            failures,
        ]

    accuracy = (
        f"{result.correct_fields / result.expected_fields:.0%}"
        if result.expected_fields
        else "n/a"
    )
    flags = (
        f"{result.flags_caught}/{result.expected_flags}"
        if result.expected_flags
        else f"{result.flags_caught} (not scored)"
    )
    return [
        result.file_name,
        result.method,
        accuracy,
        f"{result.correct_fields}/{result.expected_fields}",
        flags,
        f"{latency}s",
        failures,
    ]


def _table_headers(has_truth: bool) -> list[str]:
    if has_truth:
        return [
            "PDF",
            "Method",
            "Exact accuracy",
            "Fields",
            "Flags caught",
            "Latency",
            "Failure modes",
        ]
    return [
        "PDF",
        "Method",
        "Populated fields",
        "Compliance flags",
        "Latency",
        "Failure modes",
    ]


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    def escape(value: str) -> str:
        return value.replace("|", r"\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(escape(value) for value in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def run_benchmark(
    sample_dir: Path = SAMPLE_DIR,
    ground_truth_dir: Path = GROUND_TRUTH_DIR,
    *,
    mode: str = "regex-only",
    model: str = DEFAULT_MODEL,
) -> tuple[list[BenchmarkResult], bool]:
    pdfs = sorted(sample_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found in {sample_dir}")

    results = []
    has_truth = False
    methods = ("regex-only", "hybrid-llm") if mode == "compare" else (mode,)

    for pdf_path in pdfs:
        reference_path = ground_truth_dir / f"{pdf_path.stem}.json"
        reference = (
            RFQExtraction.model_validate_json(reference_path.read_text(encoding="utf-8"))
            if reference_path.is_file()
            else None
        )
        has_truth = has_truth or reference is not None

        for method in methods:
            started = time.perf_counter()
            error = None
            warnings: list[str] = []

            try:
                extraction, diagnostics = extract_pdf(
                    pdf_path,
                    regex_only=(method == "regex-only"),
                    model=model,
                )
                warnings = diagnostics.warnings
            except Exception as exc:
                error = str(exc)
                extraction = RFQExtraction(confidence_notes=f"Extraction failed: {error}")

            latency = time.perf_counter() - started
            if reference is None:
                correct, expected, flags_caught, expected_flags = (
                    0,
                    0,
                    len(extraction.compliance_flags),
                    0,
                )
            else:
                correct, expected, flags_caught, expected_flags = _score(
                    extraction, reference
                )

            results.append(
                BenchmarkResult(
                    file_name=pdf_path.name,
                    method=method,
                    extraction=extraction,
                    latency=latency,
                    correct_fields=correct,
                    expected_fields=expected,
                    flags_caught=flags_caught,
                    expected_flags=expected_flags,
                    failure_modes=_failure_modes(
                        extraction.confidence_notes, warnings, error
                    ),
                    error=error,
                )
            )

    return results, has_truth


def _render_report(
    results: list[BenchmarkResult], has_truth: bool, mode: str
) -> str:
    scoring = (
        "Exact field accuracy"
        if has_truth
        else "Populated fields (no ground truth)"
    )
    headers = _table_headers(has_truth)
    rows = [_format_result(result, has_truth) for result in results]
    pdf_count = len({result.file_name for result in results})

    lines = [
        "# RFQ extraction benchmark",
        "",
        f"- Mode: `{mode}`",
        f"- Scoring: {scoring}",
        f"- PDFs evaluated: {pdf_count}",
        f"- Ground truth available: {'yes' if has_truth else 'no'}",
        "",
        _markdown_table(headers, rows),
        "",
        "## Failure-mode notes",
        "",
        "Scanned pages and irregular table layouts are flagged when the PDF "
        "diagnostics detect them. No warning does not guarantee that every "
        "table was interpreted correctly.",
        "",
    ]

    if mode == "compare":
        lines.extend(
            [
                "## Method comparison",
                "",
                "Each PDF is processed once with regex extraction and once with "
                "hybrid LLM-plus-regex extraction. When ground truth is available, "
                "scores count exact matches for non-null scalar and compliance fields.",
                "",
            ]
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark RFQ PDF extraction.")
    parser.add_argument("--sample-dir", type=Path, default=SAMPLE_DIR)
    parser.add_argument("--ground-truth-dir", type=Path, default=GROUND_TRUTH_DIR)
    parser.add_argument(
        "--mode",
        choices=("regex-only", "hybrid-llm", "compare"),
        default="regex-only",
        help="Run the regex baseline, hybrid extraction, or both",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    console = Console()
    try:
        results, has_truth = run_benchmark(
            args.sample_dir,
            args.ground_truth_dir,
            mode=args.mode,
            model=args.model,
        )
        report = _render_report(results, has_truth, args.mode)
        args.report.write_text(report, encoding="utf-8")
    except Exception as exc:
        console.print(f"[red]Benchmark failed:[/red] {exc}")
        return 1

    table = Table(title="RFQ Extraction Benchmark")
    for header in _table_headers(has_truth):
        table.add_column(header)
    for result in results:
        table.add_row(*_format_result(result, has_truth))

    console.print(table)
    console.print(f"Markdown report written to [green]{args.report}[/green]")
    if args.mode == "compare" and not has_truth:
        console.print(
            "[yellow]No ground truth found; populated-field counts are shown, "
            "not accuracy. Add reference JSON files to score extraction quality.[/yellow]"
        )
    if any(result.error for result in results):
        console.print(
            "[red]One or more extraction runs failed; see the failure modes and report above.[/red]"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
