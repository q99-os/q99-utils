from pydantic import BaseModel


class UMReportSection(BaseModel):
    name: str
    section_order: int
    content: dict = {}
    metadata: dict = {}


class UMReport(BaseModel):
    """Report creation payload (report + full section skeleton, atomic).
    Author is resolved by UM from the caller's token."""
    report_type: str
    title: str
    metadata: dict
    sections: list[UMReportSection]


__all__ = ["UMReport", "UMReportSection"]
