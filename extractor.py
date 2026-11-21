"""PDF extraction and regex/LLM-backed RFQ field extraction."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import pdfplumber
from dotenv import load_dotenv
from google import genai
from rich.console import Console

from schema import RFQExtraction

DEFAULT_MODEL = "gemini-3.8-flash"
COMPLIANCE_TERMS = (
    "ITAR",
    "Berry Amendment",
    "Buy American Act",
    "DFARS",
    "First Article Testing",
    "QPL",
)

NSN_RE = re.compile(r"\b\d{4}-\d{2}-\d{3}-\d{4}\b")
SOLICITATION_RE = re.compile(
    r"\b[A-Z]{2,5}\d[A-Z0-9]{1,5}-\d{2}-[A-Z]-[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b",
    re.IGNORECASE,
)
MIL_STD_RE = re.compile(
    r"\bMIL[\s-]*STD[\s-]*(\d{3,5}(?:-\s*[A-Z0-9]+)*)\b", re.IGNORECASE
)
CAGE_RE = re.compile(
    r"\b(?:CAGE(?:\s+Code)?|CAGE\s*#)\s*[:#]?\s*([A-Z0-9]{5})\b", re.IGNORECASE
)
PART_RE = re.compile(
    r"\b(?:Part(?:\s+Number|\s+No\.?)?|P/N)\s*[:#]?\s*([A-Z0-9][A-Z0-9./_-]{1,})",
    re.IGNORECASE,
)
QUANTITY_RE = re.compile(r"\b(?:Quantity|Qty)\s*[:#]?\s*([\d,]+)\b", re.IGNORECASE)
UNIT_RE = re.compile(
    r"\b(?:Unit of Issue|U/I)\s*[:#]?\s*([A-Z]{1,4})\b", re.IGNORECASE
)
QUANTITY_UNIT_RE = re.compile(
    r"\b(?:Quantity|Qty)\s*[:#]?\s*[\d,]+\s+([A-Z]{1,4})\b", re.IGNORECASE
)
DELIVERY_RE = re.compile(
    r"\b(\d{1,4})\s*(?:calendar\s+)?days?\s*(?:A\.?R\.?O\.?|after receipt of order)\b",
    re.IGNORECASE,
)
DELIVERY_REVERSE = re.compile(
    r"\b(?:Delivery|Deliver)\s*(?:within|in)?\s*(\d{1,4})\s*days?\b", re.IGNORECASE
)


@dataclass
class PDFContent:
    text: str
    scanned_pages: list[int] = field(default_factory=list)
    ambiguous_table_pages: list[int] = field(default_factory=list)
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExtractionDiagnostics:
    scanned_pages: list[int] = field(default_factory=list)
    ambiguous_table_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _serialize_table(table: list[list[str | None]], page_number: int) -> tuple[str, bool]:
    rows = [[(cell or "").replace("\n", " ").strip() for cell in row] for row in table]
    rows = [row for row in rows if any(row)]
    if not rows:
        return "", False
    width_counts = {len(row) for row in rows}
    nonempty_counts = [sum(bool(cell) for cell in row) for row in rows]
    ambiguous = len(width_counts) > 1 or any(count <= 1 for count in nonempty_counts[1:])
    output = [f"[TABLE page {page_number}]"]
    output.extend(" | ".join(row) for row in rows)
    return "\n".join(output), ambiguous


def extract_pdf_content(pdf_path: str | Path) -> PDFContent:
    """Extract page text and tables, using PyMuPDF text when pdfplumber is sparse."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    plumber_pages: list[str] = []
    table_fragments: list[str] = []
    ambiguous_pages: set[int] = set()
    warnings: list[str] = []
    plumber_error: Exception | None = None

    try:
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                plumber_pages.append(page_text)
                try:
                    tables = page.extract_tables() or []
                    for table in tables:
                        serialized, ambiguous = _serialize_table(table, page_number)
                        if serialized:
                            table_fragments.append(serialized)
                        if ambiguous:
                            ambiguous_pages.add(page_number)
                except Exception as exc:
                    warnings.append(f"Could not extract tables from page {page_number}: {exc}")
    except Exception as exc:
        plumber_error = exc
        warnings.append(f"pdfplumber failed; using PyMuPDF text fallback: {exc}")

    fitz_pages: list[str] = []
    scanned_pages: list[int] = []
    try:
        with pymupdf.open(path) as document:
            page_count = len(document)
            for page_number, page in enumerate(document, start=1):
                fallback_text = page.get_text("text") or ""
                fitz_pages.append(fallback_text)
                page_area = max(float(page.rect.width * page.rect.height), 1.0)
                char_density = len(fallback_text.strip()) / page_area
                has_images = bool(page.get_images(full=True))
                if has_images and (len(fallback_text.strip()) < 40 or char_density < 0.00015):
                    scanned_pages.append(page_number)
                lines = [
                    line.strip()
                    for line in fallback_text.splitlines()
                    if re.search(r"\s{2,}", line) and len(line.split()) >= 3
                ]
                header_index = next(
                    (
                        index for index, line in enumerate(lines)
                        if re.search(r"\b(?:ITEM\s*/\s*NSN|LINE ITEM)\b", line, re.IGNORECASE)
                    ),
                    None,
                )
                if header_index is not None:
                    table_lines = lines[header_index:header_index + 4]
                    column_counts = [len(re.split(r"\s{2,}", line)) for line in table_lines]
                    broken_identifier = any(
                        re.search(r"\b\d{4}-\d{2}-\s{2,}", line)
                        or re.match(r"\d{3}-\d{4}\s{2,}", line)
                        for line in table_lines[1:]
                    )
                    if len(set(column_counts)) > 1 or broken_identifier:
                        ambiguous_pages.add(page_number)
    except Exception as exc:
        if plumber_error is not None:
            raise RuntimeError(
                f"Unable to read {path} with pdfplumber ({plumber_error}) or PyMuPDF ({exc})"
            ) from exc
        raise RuntimeError(f"Unable to inspect PDF {path} with PyMuPDF: {exc}") from exc

    page_texts: list[str] = []
    for index in range(page_count):
        primary = plumber_pages[index] if index < len(plumber_pages) else ""
        fallback = fitz_pages[index] if index < len(fitz_pages) else ""
        page_texts.append(primary if len(primary.strip()) >= len(fallback.strip()) else fallback)

    blocks = [
        f"[PAGE {index + 1}]\n{page_text}"
        for index, page_text in enumerate(page_texts)
        if page_text.strip()
    ]
    blocks.extend(table_fragments)
    if scanned_pages:
        warnings.append("Low text density on image-containing scanned page(s): " +
                        ", ".join(map(str, scanned_pages)))
    if ambiguous_pages:
        warnings.append("Potentially misaligned or irregular table(s) on page(s): " +
                        ", ".join(map(str, sorted(ambiguous_pages))))
    return PDFContent(
        text="\n\n".join(blocks),
        scanned_pages=scanned_pages,
        ambiguous_table_pages=sorted(ambiguous_pages),
        page_count=page_count,
        warnings=warnings,
    )


def regex_hints(text: str) -> dict[str, list[str]]:
    """Return deterministic anchor matches used to ground the LLM prompt."""
    return {
        "nsn": list(dict.fromkeys(NSN_RE.findall(text))),
        "solicitation_number": list(dict.fromkeys(SOLICITATION_RE.findall(text))),
        "mil_std_packaging": [
            "MIL-STD-" + re.sub(r"[\s-]+", "-", match).strip("-").upper()
            for match in dict.fromkeys(MIL_STD_RE.findall(text))
        ],
    }


def regex_extract(text: str) -> RFQExtraction:
    """Extract the fields that can be identified with deterministic patterns."""
    hints = regex_hints(text)
    quantity_match = QUANTITY_RE.search(text)
    delivery_match = DELIVERY_RE.search(text) or DELIVERY_REVERSE.search(text)
    flags = [term for term in COMPLIANCE_TERMS if re.search(re.escape(term), text, re.IGNORECASE)]
    unit_match = UNIT_RE.search(text) or QUANTITY_UNIT_RE.search(text)
    return RFQExtraction(
        solicitation_number=(hints["solicitation_number"] or [None])[0],
        nsn=(hints["nsn"] or [None])[0],
        cage_code=(CAGE_RE.search(text).group(1).upper() if CAGE_RE.search(text) else None),
        part_number=(PART_RE.search(text).group(1) if PART_RE.search(text) else None),
        quantity=int(quantity_match.group(1).replace(",", "")) if quantity_match else None,
        unit_of_issue=unit_match.group(1).upper() if unit_match else None,
        delivery_days_aro=int(delivery_match.group(1)) if delivery_match else None,
        mil_std_packaging=(hints["mil_std_packaging"] or [None])[0],
        compliance_flags=flags,
        confidence_notes="",
    )


def _merge_regex_fallbacks(result: RFQExtraction, baseline: RFQExtraction) -> RFQExtraction:
    fields = (
        "solicitation_number",
        "nsn",
        "cage_code",
        "part_number",
        "quantity",
        "unit_of_issue",
        "delivery_days_aro",
        "mil_std_packaging",
    )
    values = result.model_dump()
    for name in fields:
        if values[name] is None:
            values[name] = getattr(baseline, name)
    values["compliance_flags"] = list(
        dict.fromkeys([*result.compliance_flags, *baseline.compliance_flags])
    )
    return RFQExtraction.model_validate(values)


def _append_diagnostic_notes(
    result: RFQExtraction, content: PDFContent
) -> RFQExtraction:
    notes = [result.confidence_notes.strip()] if result.confidence_notes.strip() else []
    if content.scanned_pages:
        notes.append("Scanned or low-text-density page(s): " +
                     ", ".join(map(str, content.scanned_pages)))
    if content.ambiguous_table_pages:
        notes.append("Ambiguous table layout on page(s): " +
                     ", ".join(map(str, content.ambiguous_table_pages)))
    missing = [
        name for name in ("solicitation_number", "nsn", "quantity")
        if getattr(result, name) is None
    ]
    if missing:
        notes.append("Missing critical field(s): " + ", ".join(missing))
    return result.model_copy(update={"confidence_notes": "; ".join(notes)})


def _llm_extract(text: str, hints: dict[str, list[str]], model: str) -> RFQExtraction:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is required for hybrid extraction. Set it in the environment "
            "or a .env file, or use --regex-only."
        )
    client = genai.Client(api_key=api_key)
    prompt = (
        "Extract only facts explicitly present in this US government solicitation. "
        "Return null for unknown scalar fields and an empty list when no listed compliance "
        "terms occur. Preserve identifier spelling; normalize NSNs to XXXX-XX-XXX-XXXX "
        "and MIL-STD packaging codes to MIL-STD-... . Do not infer missing values. "
        "Note uncertainty in confidence_notes.\n\n"
        f"Regex anchor hints:\n{json.dumps(hints, indent=2)}\n\n"
        f"Extracted solicitation text and tables:\n{text}"
    )
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": RFQExtraction,
        },
    )
    if response.text is None:
        raise RuntimeError("Gemini did not return structured extraction.")
    return RFQExtraction.model_validate_json(response.text)


def extract_pdf(
    pdf_path: str | Path,
    *,
    regex_only: bool = False,
    model: str = DEFAULT_MODEL,
) -> tuple[RFQExtraction, ExtractionDiagnostics]:
    content = extract_pdf_content(pdf_path)
    baseline = regex_extract(content.text)
    result = baseline if regex_only else _merge_regex_fallbacks(
        _llm_extract(content.text, regex_hints(content.text), model), baseline
    )
    result = _append_diagnostic_notes(result, content)
    return result, ExtractionDiagnostics(
        scanned_pages=content.scanned_pages,
        ambiguous_table_pages=content.ambiguous_table_pages,
        warnings=content.warnings,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract structured data from a DLA RFQ PDF.")
    parser.add_argument("pdf", type=Path, help="Path to the solicitation PDF")
    parser.add_argument("--regex-only", action="store_true", help="Use deterministic regex baseline")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"Gemini model (default: {DEFAULT_MODEL})"
    )
    parser.add_argument("--output", type=Path, help="Write extraction JSON to this path")
    args = parser.parse_args(argv)
    console = Console(stderr=True)
    try:
        result, diagnostics = extract_pdf(
            args.pdf, regex_only=args.regex_only, model=args.model
        )
    except Exception as exc:
        console.print(f"[red]Extraction failed:[/red] {exc}")
        return 1
    serialized = result.model_dump_json(indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
        console.print(f"[green]Wrote extraction to[/green] {args.output}")
    else:
        print(serialized)
    for warning in diagnostics.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
