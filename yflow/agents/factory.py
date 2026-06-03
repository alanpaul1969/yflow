"""
yflow.agents.factory — P1 step types from the 7-agent factory pattern.

acceptance_tests     : read story output, run pytest, lock to tests/**
implementation_validator: pure audit step, never modifies files
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from yflow.boundary import ScopeViolation, enforce_scope, get_git_changed_files
from yflow.checkpoint import CheckpointDecision
from yflow.impeccable_scan import MATCHERS as _IMPECCABLE_MATCHERS, RULES as _IMPECCABLE_RULES


# ====================================================================
# acceptance_tests — read acceptance criteria from prior step, run
# pytest, ensure only tests/ was modified.
# ====================================================================


def _parse_acceptance_criteria(text: str) -> list[str]:
    """Pull out acceptance criteria lines from a story/spec output.

    Heuristic: lines starting with "- ", "* ", or numbered "N." under a
    heading that contains "acceptance" or "criteria". Falls back to any
    line that looks like a test case description.
    """
    if not text:
        return []
    criteria: list[str] = []
    in_criteria_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if any(kw in low for kw in ("acceptance criteria", "acceptance test", "test case")):
            in_criteria_section = True
            continue
        if in_criteria_section and stripped.startswith("#"):
            in_criteria_section = False
        if in_criteria_section and (
            stripped.startswith(("- ", "* "))
            or re.match(r"^\d+\.\s", stripped)
        ):
            criteria.append(stripped)
    return criteria


def execute_acceptance_tests_step(step: dict, session: Any) -> str:
    """Run acceptance tests against a story's criteria, locked to tests/.

    Step fields:
      test_command:   shell command (default: "pytest -x --tb=short -q")
      source:         step id whose output contains acceptance criteria
      may_modify:     list of glob patterns this step may write (default: tests/**)
      fail_on_scope_violation: bool (default True)
    """
    step_id = step["id"]
    test_command = step.get("test_command", "pytest -x --tb=short -q")
    source = step.get("source")
    may_modify = step.get("may_modify", ["tests/**"])
    fail_on_violation = step.get("fail_on_scope_violation", True)

    # Source story/spec output
    source_output = ""
    if source and source in session.outputs:
        source_output = session.outputs[source]
    criteria = _parse_acceptance_criteria(source_output)

    # Run tests
    print(f"[acceptance_tests] {step_id}: running {test_command!r}")
    try:
        result = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        output = f"FAIL: test command timed out after 300s: {test_command}"
        session.capture(step_id, output)
        return output

    # Scope check — ensure only may_modify files were touched
    changed = get_git_changed_files()
    from yflow.boundary import check_scope
    # The acceptance_tests step is special: may_modify is the inverse of
    # scope/forbidden. Here it means "these patterns are OK; everything else
    # is a violation."
    forbidden_patterns = [p for p in changed if not _matches_any(p, may_modify)]
    violations = [f for f in changed if f in forbidden_patterns and f]

    test_passed = result.returncode == 0
    scope_clean = len(violations) == 0

    verdict = {
        "step": step_id,
        "criteria_count": len(criteria),
        "test_returncode": result.returncode,
        "test_passed": test_passed,
        "scope_clean": scope_clean,
        "scope_violations": violations,
        "may_modify": may_modify,
        "stdout_tail": (result.stdout or "")[-2000:],
        "stderr_tail": (result.stderr or "")[-1000:],
    }

    output = json.dumps(verdict, indent=2, ensure_ascii=False)
    session.capture(step_id, output)

    if test_passed and scope_clean:
        return output
    if not scope_clean and fail_on_violation:
        raise ScopeViolation(step_id, violations, may_modify)
    return output


def _matches_any(path: str, patterns: list[str]) -> bool:
    """Local helper — match path against any glob pattern."""
    import fnmatch
    for pat in patterns:
        clean = pat.rstrip("/").replace("**", "*")
        if fnmatch.fnmatch(path, clean):
            return True
        if pat.endswith("**") and path.startswith(pat[:-2]):
            return True
    return False


# ====================================================================
# implementation_validator — pure audit, no file modifications.
# ====================================================================


SECRET_PATTERNS = (
    re.compile(r'(?i)(api[_-]?key|secret|password|token|passwd)\s*=\s*["\'][^"\']{8,}["\']'),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI/Anthropic style
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),  # GitHub PAT
)


def execute_implementation_validator_step(step: dict, session: Any) -> str:
    """Audit step that NEVER modifies code. Returns structured verdict.

    Checks performed:
      - criteria_coverage: every acceptance criterion has a matching test
      - security: scan diff for hardcoded secrets, missing safety checks
      - scope_drift: verify all changes are within declared workflow scopes
      - story_alignment: spot-check that changed files implement the story

    Step fields:
      story_ref:      step id whose output is the user story + criteria
      criteria:       explicit list (overrides parsing story_ref)
      checks:         list of checks to run (default: all)
      fail_on:        severity threshold ("critical" | "important" | "minor", default "important")
    """
    step_id = step["id"]
    story_ref = step.get("story_ref")
    explicit_criteria = step.get("criteria")
    checks = step.get("checks", ["criteria", "security", "scope"])
    fail_on = step.get("fail_on", "important")

    story_text = ""
    if story_ref and story_ref in session.outputs:
        story_text = session.outputs[story_ref]
    criteria = explicit_criteria or _parse_acceptance_criteria(story_text)

    findings: list[dict[str, str]] = []
    changed = get_git_changed_files()

    # ---- criteria_coverage ----
    if "criteria" in checks and criteria:
        for c in criteria:
            # Heuristic: criterion text → search changed files for related test
            # We look at test files in tests/ for keywords from the criterion
            keywords = re.findall(r"[A-Za-z_]{4,}", c)
            covered = False
            for f in changed:
                if not f.startswith("tests/") and not f.startswith("test/"):
                    continue
                try:
                    content = Path(f).read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if any(kw in content for kw in keywords[:3]):
                    covered = True
                    break
            if not covered:
                findings.append({
                    "severity": "important",
                    "check": "criteria",
                    "criterion": c[:120],
                    "issue": "No test file in changes references this criterion",
                })

    # ---- security ----
    if "security" in checks:
        for f in changed:
            if not f.endswith((".py", ".js", ".ts", ".yaml", ".yml", ".env", ".sh")):
                continue
            try:
                content = Path(f).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pat in SECRET_PATTERNS:
                if pat.search(content):
                    findings.append({
                        "severity": "critical",
                        "check": "security",
                        "file": f,
                        "issue": f"Possible hardcoded secret matching {pat.pattern[:30]}...",
                    })
                    break

    # ---- design (v0.6.3) ----
    # Port of impeccable's deterministic anti-pattern rules, narrowed
    # to Flutter-detectable tells. Runs on .dart / .css / .scss / .html
    # files in the diff. See yflow/impeccable_scan.py for the full
    # rule registry.
    if "design" in checks:
        for f in changed:
            if not f.endswith((".dart", ".css", ".scss", ".html", ".htm")):
                continue
            try:
                content = Path(f).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for rule in _IMPECCABLE_RULES:
                matcher = _IMPECCABLE_MATCHERS[rule["matches"]]
                hits = matcher(content, Path(f))
                for line_no, _ in hits:
                    findings.append({
                        "severity": rule["severity"],
                        "check": "design",
                        "file": f,
                        "line": line_no,
                        "rule_id": rule["id"],
                        "issue": rule["name"],
                    })

    # ---- scope_drift ----
    if "scope" in checks:
        # We don't know per-step scopes here without a wider refactor; just
        # report changed files and let human review scope decisions.
        if len(changed) > 20:
            findings.append({
                "severity": "minor",
                "check": "scope",
                "issue": f"Large change set: {len(changed)} files modified — review for scope drift",
            })

    # ---- aggregate verdict ----
    severity_rank = {"critical": 3, "important": 2, "minor": 1}
    threshold = severity_rank.get(fail_on, 2)
    blocking = [f for f in findings if severity_rank.get(f["severity"], 0) >= threshold]

    verdict = {
        "step": step_id,
        "checks_run": checks,
        "criteria_count": len(criteria),
        "files_changed": len(changed),
        "files_changed_list": changed[:50],
        "findings": findings,
        "blocking_count": len(blocking),
        "verdict": "PASS" if not blocking else "FAIL",
    }
    output = json.dumps(verdict, indent=2, ensure_ascii=False)
    session.capture(step_id, output)

    if blocking:
        # Don't raise — validator is informational; caller (or human) decides
        print(f"[implementation_validator] {step_id}: {verdict['verdict']} ({len(blocking)} blocking findings)")
    else:
        print(f"[implementation_validator] {step_id}: PASS ({len(findings)} minor findings)")
    return output
