"""
Generation module: schema-constrained output
Each claim-bearing field must reference evidence span identifiers
"""

from .generator import (
    SYSTEM_PROMPT,
    build_generation_prompt,
    generate_pitch,
    generate_pitch_with_llm,
)

__all__ = [
    "SYSTEM_PROMPT",
    "build_generation_prompt",
    "generate_pitch",
    "generate_pitch_with_llm",
]
