"""Compatibility wrapper for research logging helpers.

This module intentionally re-exports the canonical implementation from
`gpt_researcher.utils.logging_config` to avoid duplicate definitions.
"""

from gpt_researcher.utils.logging_config import (  # noqa: F401
    JSONResearchHandler,
    get_json_handler,
    get_research_logger,
    setup_research_logging,
)
