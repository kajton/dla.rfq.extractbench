"""Generate three synthetic DLA-style RFQ PDFs and matching JSON references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf

from schema import RFQExtraction


def _write_pdf(path: Path, pages: list[list[tuple[str, tuple[float, float], int]]]) -> None:
    document = pymupdf.open()
    for blocks in pages:
        page = document.new_page(width=612, height=792)
        for text, position, size in blocks:
            page.insert_text(position, text, fontsize=size, fontname="helv")
    document.save(path)
    document.close()


def _write_ground_truth(path: Path, extraction: RFQExtraction) -> None:
    path.write_text(extraction.model_dump_json(indent=2) + "\n", encoding="utf-8")


def generate(output_dir: Path = Path("sample_rfqs"), ground_truth_dir: Path = Path("ground_truth")) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ground_truth_dir.mkdir(parents=True, exist_ok=True)

    clean = RFQExtraction(
        solicitation_number="SPE4A6-26-T-1042",
        nsn="1560-00-123-4567",
        cage_code="1A2B3",
        part_number="PN-4402",
        quantity=24,
        unit_of_issue="EA",
        delivery_days_aro=45,
        mil_std_packaging="MIL-STD-2073-1E",
        compliance_flags=["DFARS"],
        confidence_notes="",
    )
    _write_pdf(output_dir / "clean_digital.pdf", [[
        ("DEFENSE LOGISTICS AGENCY - REQUEST FOR QUOTATION", (50, 50), 13),
        ("Solicitation Number: SPE4A6-26-T-1042", (50, 85), 10),
        ("NSN: 1560-00-123-4567    Quantity: 24    Unit of Issue: EA", (50, 108), 10),
        ("Part Number: PN-4402    CAGE Code: 1A2B3", (50, 130), 10),
        ("Delivery: 45 days ARO", (50, 152), 10),
        ("Packaging: MIL-STD-2073-1E", (50, 174), 10),
        ("Contract terms include applicable DFARS clauses.", (50, 208), 10),
        ("LINE ITEM     DESCRIPTION                    QTY       U/I", (50, 265), 10),
        ("0001          Actuator assembly, aircraft    24        EA", (50, 284), 10),
    ]])
    _write_ground_truth(ground_truth_dir / "clean_digital.json", clean)

    tricky = RFQExtraction(
        solicitation_number="SPE7L1-26-T-2208",
        nsn="5340-01-987-6543",
        cage_code="7XY89",
        part_number="BRK-88",
        quantity=12,
        unit_of_issue="BX",
        delivery_days_aro=60,
        mil_std_packaging="MIL-STD-2073-1E",
        compliance_flags=["Berry Amendment", "First Article Testing", "ITAR"],
        confidence_notes="Packaging code is split across lines; clause text is multi-line.",
    )
    _write_pdf(output_dir / "packaging_clauses.pdf", [[
        ("DLA - REQUEST FOR QUOTATION", (48, 48), 13),
        ("Solicitation No.: SPE7L1-26-T-2208", (48, 80), 10),
        ("National Stock Number (NSN): 5340-01-987-6543", (48, 101), 10),
        ("Part No.: BRK-88     CAGE: 7XY89", (48, 122), 10),
        ("Qty: 12 BX", (48, 143), 10),
        ("Delivery required 60 days after receipt of order (ARO).", (48, 164), 10),
        ("Packaging requirement:", (48, 200), 10),
        ("MIL-STD-2073-", (70, 220), 10),
        ("1E, Method 10, preservation and unit pack as specified.", (70, 238), 10),
        ("Berry Amendment: qualifying domestic source restrictions apply.", (48, 285), 10),
        ("First Article Testing is required before production quantities.", (48, 307), 10),
        ("This item and technical data are subject to ITAR controls.", (48, 329), 10),
        ("LINE ITEM       DESCRIPTION                 QUANTITY / UOM", (48, 390), 10),
        ("0001            Retaining bracket           12 BX", (48, 409), 10),
    ]])
    _write_ground_truth(ground_truth_dir / "packaging_clauses.json", tricky)

    noisy = RFQExtraction(
        solicitation_number="SPE4A6-26-T-7315",
        nsn="5998-01-234-9876",
        cage_code="4QWER",
        part_number="PCB-100A",
        quantity=8,
        unit_of_issue="KT",
        delivery_days_aro=30,
        mil_std_packaging="MIL-STD-2073-1E",
        compliance_flags=["Buy American Act", "QPL"],
        confidence_notes="Simulated broken-layout, multi-column line-item table.",
    )
    _write_pdf(output_dir / "noisy_layout.pdf", [[
        ("DEFENSE LOGISTICS AGENCY  |  RFQ / PAGE 1", (42, 44), 12),
        ("Solicitation: SPE4A6-26-T-7315", (42, 78), 9),
        ("NSN 5998-01-234-9876", (42, 98), 9),
        ("CAGE Code: 4QWER", (350, 78), 9),
        ("Part Number PCB-100A", (350, 98), 9),
        ("Qty 8       Unit of Issue KT       Delivery 30 days ARO", (42, 125), 9),
        ("MIL-STD-2073-1E packaging applies.", (42, 147), 9),
        ("Buy American Act provisions apply. Item must be listed on the QPL.", (42, 169), 9),
        ("ITEM / NSN         DESCRIPTION           QTY       UNIT       SHIP TO", (42, 230), 9),
        ("0001 / 5998-01-     Circuit card          8         KT         DLA", (42, 249), 9),
        ("234-9876             assembly PCB-100A     30 DAYS   ARO        DEPOT", (42, 266), 9),
        ("Table continuation: MIL-STD-2073-1E packaging, see note 4.", (42, 311), 9),
        ("NOTE 4: Preserve and pack each kit in accordance with the cited standard.", (42, 333), 9),
    ]])
    _write_ground_truth(ground_truth_dir / "noisy_layout.json", noisy)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic RFQ benchmark PDFs.")
    parser.add_argument("--output-dir", type=Path, default=Path("sample_rfqs"))
    parser.add_argument("--ground-truth-dir", type=Path, default=Path("ground_truth"))
    args = parser.parse_args()
    generate(args.output_dir, args.ground_truth_dir)
    print(f"Generated 3 synthetic RFQs in {args.output_dir} and references in {args.ground_truth_dir}.")


if __name__ == "__main__":
    main()
