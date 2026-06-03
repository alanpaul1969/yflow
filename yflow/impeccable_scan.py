#!/usr/bin/env python3
"""
YOUR_PROJECT design-tell scanner (Flutter-aware port of impeccable rules).

Scans .dart files in a Flutter project for the most common AI/design
tells. Output: count + file:line per tell. Maps to impeccable's
deterministic rule registry.

Run: python3 impeccable_flutter_scan.py <project_lib_dir>
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path


# === Rule registry (port of impeccable's 27 deterministic rules, ===
# === narrowed to the ones detectable from Flutter .dart files) ===

RULES = [
    {
        "id": "ghost-card",
        "name": "Ghost card (border + heavy shadow)",
        "severity": "high",
        "matches": "border_plus_heavy_shadow",
    },
    {
        "id": "over-rounded",
        "name": "Over-rounded surface (borderRadius ≥ 24 on non-pill)",
        "severity": "high",
        "matches": "border_radius_24_plus",
    },
    {
        "id": "gradient-text",
        "name": "Gradient text (ShaderMask on Text)",
        "severity": "medium",
        "matches": "shader_mask_text",
    },
    {
        "id": "glassmorphism-default",
        "name": "Glassmorphism as default (BackdropFilter blur)",
        "severity": "medium",
        "matches": "backdrop_filter_blur",
    },
    {
        "id": "side-stripe-border",
        "name": "Side-stripe border (Border with side + color)",
        "severity": "high",
        "matches": "side_border_only",
    },
    {
        "id": "eyebrow-caps",
        "name": "Tiny uppercase tracked eyebrow (letterSpacing + fontSize ≤ 12)",
        "severity": "low",
        "matches": "eyebrow_text_style",
    },
    {
        "id": "hero-metric-gradient",
        "name": "Hero-metric gradient (LinearGradient as accent on big text)",
        "severity": "medium",
        "matches": "linear_gradient_on_metric",
    },
    {
        "id": "cream-body-bg",
        "name": "Cream/sand body background (low-chroma warm tint)",
        "severity": "low",
        "matches": "cream_background",
    },
]


# === Pattern matchers ===

def check_border_plus_heavy_shadow(content: str, path: Path):
    """Ghost card: Border.all(...) + BoxShadow blur > 16 on same widget.

    In Flutter this typically shows as a Container or DecoratedBox with
    both decoration.border and boxShadow with blur > 16.
    """
    findings = []
    # Look for: border: ... AND boxShadow: ... within ~30 lines
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if "BoxShadow(" in line or "boxShadow:" in line:
            # Find the blur value
            m = re.search(r"blurRadius:\s*(\d+(?:\.\d+)?)", line)
            if m and float(m.group(1)) > 16:
                # Look back for border in nearby lines
                start = max(0, i - 30)
                nearby = "\n".join(lines[start:i + 1])
                if "Border.all(" in nearby or "border: Border(" in nearby:
                    findings.append((i + 1, line.strip()[:120]))
    return findings


def check_border_radius_24_plus(content: str, path: Path):
    """borderRadius ≥ 24 on what looks like a card (not a button/pill).

    Pills (fully rounded via BorderRadius.circular with very high
    value) and small circular avatars are OK. Cards/surfaces should
    be 12-16 max per impeccable.
    """
    findings = []
    for i, line in enumerate(content.splitlines()):
        # Match `borderRadius: BorderRadius.circular(24)` etc.
        m = re.search(r"borderRadius:\s*(?:BorderRadius\.circular\(|BorderRadius\.only\([^)]*\)|BorderRadius\.all\()\s*(\d+)", line)
        if not m:
            # Also catch: borderRadius: BorderRadius.circular(X) directly
            m = re.search(r"BorderRadius\.circular\((\d+)\)", line)
        if m:
            v = int(m.group(1))
            if v >= 24:
                findings.append((i + 1, f"borderRadius: {v} — {line.strip()[:100]}"))
    return findings


def check_shader_mask_text(content: str, path: Path):
    """Gradient text: ShaderMask wrapping a Text or using blendMode on Text.

    Per impeccable: gradient text is decorative, never meaningful. Use
    a single solid color instead.
    """
    findings = []
    for i, line in enumerate(content.splitlines()):
        if "ShaderMask" in line or "shaderCallback" in line:
            findings.append((i + 1, line.strip()[:120]))
    return findings


def check_backdrop_filter_blur(content: str, path: Path):
    """Glassmorphism as default: BackdropFilter with ImageFilter.blur.

    Per impeccable: Blurs and glass cards used decoratively. Rare and
    purposeful, or nothing.
    """
    findings = []
    for i, line in enumerate(content.splitlines()):
        if "BackdropFilter" in line or "ImageFilter.blur" in line:
            findings.append((i + 1, line.strip()[:120]))
    return findings


def check_side_border_only(content: str, path: Path):
    """Side-stripe border: Border with only one side colored (the absolute ban).

    Pattern: Border(left: BorderSide(color: ..., width: > 1)) or
    Border(top: BorderSide(color: ..., width: > 1))
    """
    findings = []
    for i, line in enumerate(content.splitlines()):
        # Match `Border(left: BorderSide(color:` with width > 1
        m = re.search(
            r"Border\((left|right|top|bottom):\s*BorderSide\([^)]*width:\s*(\d+(?:\.\d+)?)",
            line,
        )
        if m and float(m.group(2)) > 1:
            findings.append((i + 1, f"side-stripe ({m.group(1)}): {line.strip()[:100]}"))
        # Also: `border: Border(left: BorderSide(color: ...))` shorthand
        if "borderSide" in line.lower() and ("left:" in line or "right:" in line):
            if "width" not in line or "width: 1" not in line:
                findings.append((i + 1, f"side-stripe: {line.strip()[:100]}"))
    return findings


def check_eyebrow_text_style(content: str, path: Path):
    """Tiny uppercase tracked eyebrow: small font + letterSpacing.

    The 2023-era kicker: small all-caps text with wide tracking above
    every section. Saturated AI scaffold.
    """
    findings = []
    # We look for blocks where fontSize ≤ 12 + letterSpacing > 0
    # in the same TextStyle. Heuristic: lines within 5 of each other
    lines = content.splitlines()
    for i, line in enumerate(lines):
        m = re.search(r"fontSize:\s*(\d+(?:\.\d+)?)", line)
        if m and float(m.group(1)) <= 12:
            # Check next 8 lines for letterSpacing
            for j in range(i, min(i + 8, len(lines))):
                if "letterSpacing:" in lines[j] and "letterSpacing: 0" not in lines[j]:
                    findings.append((i + 1, f"fontSize:{m.group(1)} + letterSpacing — {line.strip()[:100]}"))
                    break
    return findings


def check_linear_gradient_on_metric(content: str, path: Path):
    """Hero-metric: LinearGradient with the metric-number-look colors.

    Big number + small label + gradient accent. We just flag any
    LinearGradient used decoratively (not as a background for a card
    or surface). Heuristic: LinearGradient inside TextStyle or
    ShaderMask contexts.
    """
    findings = []
    for i, line in enumerate(content.splitlines()):
        if "LinearGradient(" in line:
            # Check if it's wrapped in a TextStyle / Text context
            start = max(0, i - 10)
            nearby = "\n".join(content.splitlines()[start:i + 1])
            if "TextStyle" in nearby or "Text(" in nearby:
                findings.append((i + 1, f"LinearGradient near text — {line.strip()[:100]}"))
    return findings


def check_cream_background(content: str, path: Path):
    """Cream/sand body background: low-chroma warm tint on body/scaffold.

    The 2026 AI default per impeccable. Flag any low-chroma warm
    background color (0xFFFFF8F0, 0xFFFAF0E6, 0xFFFBF5E6, etc.).
    """
    # Hex codes of common cream/sand colors
    cream_hexes = {
        "0xfffff8f0", "0xfffaf0e6", "0xfffbf5e6", "0xfff5f5dc",
        "0xfffffaf0", "0xfffdf5e6", "0xfff0e68c", "0xffffe4c4",
    }
    findings = []
    for i, line in enumerate(content.splitlines()):
        low = line.lower()
        for h in cream_hexes:
            if h in low:
                findings.append((i + 1, f"cream hex {h} — {line.strip()[:100]}"))
                break
    return findings


# === Orchestration ===

MATCHERS = {
    "border_plus_heavy_shadow": check_border_plus_heavy_shadow,
    "border_radius_24_plus": check_border_radius_24_plus,
    "shader_mask_text": check_shader_mask_text,
    "backdrop_filter_blur": check_backdrop_filter_blur,
    "side_border_only": check_side_border_only,
    "eyebrow_text_style": check_eyebrow_text_style,
    "linear_gradient_on_metric": check_linear_gradient_on_metric,
    "cream_background": check_cream_background,
}


def scan_project(lib_dir: Path) -> dict:
    """Scan all .dart files in lib/ for design tells. Return findings."""
    results = {rule["id"]: {"rule": rule, "files": []} for rule in RULES}
    for dart_file in sorted(lib_dir.rglob("*.dart")):
        try:
            content = dart_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(dart_file.relative_to(lib_dir.parent))
        for rule in RULES:
            matcher = MATCHERS[rule["matches"]]
            hits = matcher(content, dart_file)
            if hits:
                results[rule["id"]]["files"].append((rel, hits))
    return results


def print_report(results: dict, lib_dir: Path) -> None:
    """Print a human-readable report."""
    print(f"\n{'=' * 70}")
    print(f"  Design Tell Audit — {lib_dir}")
    print(f"  (Impeccable deterministic rules, Flutter port)")
    print(f"{'=' * 70}\n")

    total_files_with_tells = set()
    total_tells = 0
    severity_count = {"high": 0, "medium": 0, "low": 0}

    # Group by severity
    by_severity = {"high": [], "medium": [], "low": []}
    for rule_id, data in results.items():
        if not data["files"]:
            continue
        sev = data["rule"]["severity"]
        count = sum(len(hits) for _, hits in data["files"])
        by_severity[sev].append((rule_id, data["rule"], count, data["files"]))
        severity_count[sev] += count
        for f, _ in data["files"]:
            total_files_with_tells.add(f)
        total_tells += count

    for sev in ("high", "medium", "low"):
        rules = by_severity[sev]
        if not rules:
            continue
        print(f"### {sev.upper()} ({sum(r[2] for r in rules)} tells across {len(rules)} rules)\n")
        for rule_id, rule, count, files in rules:
            print(f"  ❌ {rule['name']}")
            print(f"     ID: {rule_id}  |  Count: {count}  |  Files: {len(files)}")
            for f, hits in files[:5]:  # show first 5
                first_line = hits[0][0]
                print(f"     {f}:{first_line}")
            if len(files) > 5:
                print(f"     ... and {len(files) - 5} more file(s)")
            print()

    print(f"{'=' * 70}")
    print(f"  TOTAL: {total_tells} design tells across {len(total_files_with_tells)} files")
    print(f"  Breakdown: {severity_count['high']} high / {severity_count['medium']} medium / {severity_count['low']} low")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 impeccable_flutter_scan.py <lib_dir>")
        sys.exit(1)
    lib = Path(sys.argv[1])
    if not lib.exists():
        print(f"Path not found: {lib}")
        sys.exit(1)
    results = scan_project(lib)
    print_report(results, lib)
