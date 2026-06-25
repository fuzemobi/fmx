"""Benchmark prompts + answer keys, shared by the battery and reasoning runners.

All prompts are model-agnostic and graded deterministically (see harness graders).
The summarization corpus is the bundled data/sample_readme.md so results are reproducible
inside this repo, independent of any external file.
"""
from __future__ import annotations

from pathlib import Path

SAMPLE_DOC = Path(__file__).resolve().parent / "data" / "sample_readme.md"

# --- 1. summarization --------------------------------------------------------
SUMM_INSTR = """You are condensing project documentation into a SHORTER Markdown document.
RULES: (1) Use ONLY facts in the SOURCE; never invent or expand. (2) Output Markdown
prose+lists, NOT code-only. (3) Include sections: Overview, Pipeline, Prerequisites,
Installation, CLI Commands, Supported Input Formats, Project Structure. (4) Output only
the Markdown.

SOURCE:
"""


def summarization_prompt() -> str:
    return SUMM_INSTR + SAMPLE_DOC.read_text()


# --- 2. coding ---------------------------------------------------------------
CODE_PROMPT = """Create a complete, self-contained Python file using pytest. Requirements:
1. Define `to_zulu(dt)` returning a UTC "Zulu" string "YYYY-MM-DDTHH:MM:SSZ" (seconds
   precision, trailing 'Z', no microseconds, not "+00:00"). Aware datetimes convert to
   UTC; a naive datetime raises ValueError.
2. Write EXACTLY two tests: `test_good_date()` (aware dt -> exact expected string) and
   `test_bad_date()` (naive dt -> `with pytest.raises(ValueError):`). Both REQUIRED.
3. Build aware datetimes with tzinfo=timezone.utc; do NOT call timezone(timezone.utc).
4. Runs clean under pytest, standard library only.
Output ONLY the Python code — no fences, no commentary."""

# --- 3. structured JSON ------------------------------------------------------
JSON_PROMPT = """From the text below, extract a JSON object with exactly these keys:
"tadig" (string), "mcc" (integer), "mnc" (integer), "imsi" (string). Output ONLY valid
JSON, no prose, no code fences.
Text: "Partner USASN (TADIG USASN) operates on MCC 312 / MNC 380; a sample subscriber
IMSI is 312380123456789." """

JSON_EXPECTED = {"tadig": "USASN", "mcc": 312, "mnc": 380, "imsi": "312380123456789"}

# --- 4. hard reasoning (trap problems, single verifiable answer) -------------
_TAIL = "\nThink step by step, then put the final answer on its own last line as: ANSWER: <value>"

REASONING_PROBLEMS = [
    ("A",  # tiered usage + surcharge applied only above a threshold
     "A roaming data plan: the first 500 MB in a cycle are free, the next 1500 MB are "
     "$0.04/MB, and everything above 2000 MB is $0.02/MB. A subscriber used 3,200 MB. A "
     "15% surcharge then applies ONLY to the portion of the usage charges that exceeds $40 "
     "(the first $40 is not surcharged). What is the total bill?" + _TAIL,
     "90.60"),
    ("B",  # DST + timezone conversion of a call's end time
     "A call connects at 2026-03-08 01:30:00 US/Eastern and lasts 90 minutes of real "
     "elapsed time. US Eastern Daylight Time begins 2026-03-08 at 02:00 local, when clocks "
     "jump 02:00 to 03:00 (EST = UTC-5, EDT = UTC-4). Give the call's END time in UTC in "
     "the exact format YYYY-MM-DDTHH:MM:SSZ." + _TAIL,
     "08:00:00z"),
    ("C",  # constraint-satisfaction logic grid
     "Carriers A, B, C each bill in a different currency (USD, EUR, GBP) and use a different "
     "clearinghouse (CH1, CH2, CH3). Clues: (1) A does not use CH1. (2) the USD carrier uses "
     "CH3. (3) B bills in EUR. (4) C does not use CH3. (5) the GBP carrier uses CH1. Which "
     "clearinghouse does carrier A use?" + _TAIL,
     "ch3"),
    ("D",  # break-even algebra with a piecewise rate
     "Plan X costs $0.03/MB flat. Plan Y costs $20 flat for the first 800 MB and then "
     "$0.05/MB for every MB above 800. Assuming usage is above 800 MB, at exactly how many "
     "MB of usage do the two plans cost the same? Give the integer number of MB." + _TAIL,
     "1000"),
]
