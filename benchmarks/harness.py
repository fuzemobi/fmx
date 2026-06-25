"""Shared benchmark harness — backends, graders, prompts, and matrix printing.

Three backends, one purpose: figure out when the on-device fmx model is good enough
and when to escalate to a cloud or larger-local model.

- fmx          — Apple on-device via the `fmx respond` CLI (same model the MCP
                 `respond` tool calls into). Free, private, offline, small context, slow.
- cerebras     — Cerebras API (`gpt-oss-120b`, `zai-glm-4.7`). Needs CEREBRAS_API_KEY.
- ollama       — local Ollama OpenAI endpoint (e.g. `qwen3-coder:30b`). Free, offline.

Every backend returns {"text": str, "ms": int, "usage": dict}. Backends that aren't
available are skipped by the runners (see *_available()).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# backends
# ---------------------------------------------------------------------------
CEREBRAS_PRICING = {  # USD per 1M tokens (input, output)
    "gpt-oss-120b": (0.25, 0.69),
    "zai-glm-4.7": (0.40, 1.20),
}


def _load_cerebras_key() -> str | None:
    key = os.environ.get("CEREBRAS_API_KEY") or os.environ.get("CEREBRAS_APIKEY")
    if key:
        return key
    for f in (Path.home() / ".secrets/api-keys.env", Path.home() / ".env"):
        if not f.exists():
            continue
        for ln in f.read_text().splitlines():
            ln = ln.strip()
            ln = ln[len("export "):] if ln.startswith("export ") else ln
            if "=" in ln and not ln.startswith("#"):
                k, _, v = ln.partition("=")
                if k.strip() in ("CEREBRAS_API_KEY", "CEREBRAS_APIKEY"):
                    return v.strip().strip('"').strip("'")
    return None


def _post(url: str, payload: dict, headers: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    ms = round((time.time() - t0) * 1000)
    msg = d["choices"][0]["message"]
    return {"text": msg.get("content") or msg.get("reasoning") or "",
            "ms": ms, "usage": d.get("usage", {})}


def fmx_available() -> bool:
    return shutil.which("fmx") is not None


def fmx_respond(prompt: str, instructions: str | None = None, max_tokens: int = 2000) -> dict:
    """Call the on-device model via the fmx CLI (stdin prompt). $0, no usage tokens."""
    cmd = ["fmx", "respond"]
    if instructions:
        cmd += ["-i", instructions]
    cmd += ["--max-tokens", str(max_tokens), "-"]
    t0 = time.time()
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=300)
    ms = round((time.time() - t0) * 1000)
    return {"text": r.stdout.strip(), "ms": ms, "usage": {}}


def cerebras_available() -> bool:
    return _load_cerebras_key() is not None


def cerebras_chat(model: str, prompt: str, max_tokens: int = 8000,
                  temperature: float = 0.2) -> dict:
    return _post(
        "https://api.cerebras.ai/v1/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": prompt}],
         "max_tokens": max_tokens, "temperature": temperature},
        # NB: default urllib User-Agent is 403'd by Cerebras — spoof a curl UA.
        {"Authorization": f"Bearer {_load_cerebras_key()}",
         "Content-Type": "application/json", "User-Agent": "curl/8"},
    )


def cerebras_cost(model: str, usage: dict) -> float:
    if not usage or model not in CEREBRAS_PRICING:
        return 0.0
    pin, pout = CEREBRAS_PRICING[model]
    return (usage.get("prompt_tokens", 0) / 1e6 * pin
            + usage.get("completion_tokens", 0) / 1e6 * pout)


def ollama_available(host: str = "http://localhost:11434") -> bool:
    try:
        urllib.request.urlopen(host + "/api/tags", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


def ollama_chat(model: str, prompt: str, max_tokens: int = 8000, temperature: float = 0.2,
                host: str = "http://localhost:11434") -> dict:
    # The OpenAI-compat endpoint uses Ollama's default context (often ~4k unless the model
    # sets it). For long inputs, use the native /api/chat with options.num_ctx instead.
    return _post(
        host + "/v1/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": prompt}],
         "max_tokens": max_tokens, "temperature": temperature, "stream": False},
        {"Content-Type": "application/json"},
    )


# ---------------------------------------------------------------------------
# graders  (every grader is deterministic — the whole point is no eyeballing)
# ---------------------------------------------------------------------------
def strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def answer_line(text: str) -> str:
    """Grade only the model's FINAL answer line — whole-transcript matching false-passes
    when the expected token is quoted from the question (e.g. 'CH3' in a logic clue)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if "answer" in ln.lower():
            return ln
    return lines[-1] if lines else ""


def grade_reason(text: str, expected: str) -> bool:
    norm = answer_line(text).lower().replace(",", "").replace("$", "").replace(" ", "")
    return expected in norm


def grade_json(text: str, expected: dict) -> str:
    m = re.search(r"\{.*\}", strip_fence(text), re.S)
    if not m:
        return "FAIL: no JSON"
    try:
        obj = json.loads(m.group())
    except json.JSONDecodeError:
        return "FAIL: invalid JSON"
    for k, v in expected.items():
        if obj.get(k) != v:
            return f"FAIL: {k}={obj.get(k)!r}"
        if isinstance(v, int) and not isinstance(obj.get(k), int):
            return f"FAIL: {k} not int"
    return "PASS"


def grade_summary(text: str, source_words: int) -> str:
    low = text.lower()
    req = ["overview", "pipeline", "prerequisit", "installation", "cli",
           "input format", "project structure"]
    miss = [r for r in req if r not in low]
    if miss:
        return "FAIL: missing " + ",".join(miss)
    ratio = len(text.split()) / max(1, source_words)
    # only flag the degenerate cases: didn't compress at all, or dropped almost everything.
    if not 0.05 <= ratio <= 0.80:
        return f"FAIL: ratio {ratio:.0%}"
    return "PASS*"  # * = still needs a manual hallucination spot-check


def grade_code(code_text: str, workdir: Path, tag: str) -> str:
    """Write the generated test file, run pytest, AND independently verify to_zulu."""
    tag = re.sub(r"[^0-9a-zA-Z_]", "_", tag)  # filename must be a valid module name
    p = workdir / f"_gen_{tag}.py"
    p.write_text(strip_fence(code_text) + "\n")
    r = subprocess.run([sys.executable, "-m", "pytest", str(p), "-q",
                        "-o", "addopts=", "-p", "no:cacheprovider"],
                       capture_output=True, text=True)
    pytest_ok = r.returncode == 0
    ref = "ref:?"
    try:
        spec = importlib.util.spec_from_file_location(p.stem, p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = mod.to_zulu
        assert fn(datetime(2026, 6, 25, 14, 30, tzinfo=timezone.utc)) == "2026-06-25T14:30:00Z"
        est = timezone(timedelta(hours=-5))
        assert fn(datetime(2026, 6, 25, 9, 30, tzinfo=est)) == "2026-06-25T14:30:00Z"
        try:
            fn(datetime(2026, 6, 25, 14, 30))
            ref = "ref:naive-not-rejected"
        except ValueError:
            ref = "ref:PASS"
    except Exception as e:  # noqa: BLE001 - report any failure mode in the cell
        ref = f"ref:{type(e).__name__}"
    return f"{'pytest:PASS' if pytest_ok else 'pytest:FAIL'} {ref}"


# ---------------------------------------------------------------------------
# matrix printing
# ---------------------------------------------------------------------------
def print_matrix(title: str, rows: list[str], cols: list[str],
                 cell: dict[tuple[str, str], str], width: int = 22) -> None:
    print(f"\n=== {title} ===\n")
    hdr = f"{'':<14}" + "".join(f"{c:>{width}}" for c in cols)
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r:<14}" + "".join(f"{cell.get((r, c), '-'):>{width}}" for c in cols))
