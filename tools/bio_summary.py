"""Backwards-compatible imports for shared HAL summarization."""

import os

from hal_md.summarization import BioSummarizer, BioSummaryError


def summary_setting(option: str | None, name: str, default: str) -> str:
    return option or os.environ.get(name) or default
