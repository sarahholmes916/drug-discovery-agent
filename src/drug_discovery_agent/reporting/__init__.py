"""Local-only reports."""

from .report import build_report

__all__ = ["build_report"]
from .report import build_report
from .workbook import append_analysis_workbook, build_workbook_tables

__all__ = ["append_analysis_workbook", "build_report", "build_workbook_tables"]
