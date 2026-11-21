"""Structured output model for defense procurement RFQ extraction."""

from pydantic import BaseModel, Field


class RFQExtraction(BaseModel):
    """Normalized fields commonly needed to evaluate a DLA RFQ line item."""

    solicitation_number: str | None = Field(
        default=None, description="Solicitation identifier, e.g. SPE4A6-26-T-1234"
    )
    nsn: str | None = Field(
        default=None, description="13-digit National Stock Number, formatted XXXX-XX-XXX-XXXX"
    )
    cage_code: str | None = Field(
        default=None, description="Five-character CAGE code for the manufacturer or vendor"
    )
    part_number: str | None = Field(default=None, description="Manufacturer part number")
    quantity: int | None = Field(default=None, description="Solicited quantity")
    unit_of_issue: str | None = Field(
        default=None, description="Unit of issue, such as EA, BX, or KT"
    )
    delivery_days_aro: int | None = Field(
        default=None, description="Delivery time in days after receipt of order"
    )
    mil_std_packaging: str | None = Field(
        default=None, description="MIL-STD packaging requirement, if specified"
    )
    compliance_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Mentioned compliance requirements among ITAR, Berry Amendment, Buy American Act, "
            "DFARS, First Article Testing, and QPL"
        ),
    )
    confidence_notes: str = Field(
        default="", description="Ambiguous layout, scanned content, or missing critical fields"
    )
