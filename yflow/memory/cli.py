"""
CLI handlers for `yflow memory` subcommand.

Usage:
    yflow memory add <slug> [--title T] [--type T] [--tags a,b] [--body B | --from-file F]
    yflow memory get <slug> [--frontmatter-only]
    yflow memory list [--prefix NS/] [--tag X]
    yflow memory search <pattern>
    yflow memory inject <slug>... [--output FILE]
    yflow memory rm <slug> [--force]
    yflow memory mv <old> <new>
    yflow memory check [--budget N]
    yflow memory diet
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from yflow.memory.stdlib_backend import StdlibBackend
from yflow.memory.paths import default_memory_dir


def _get_backend(args) -> StdlibBackend:
    root = Path(args.memory_dir) if getattr(args, "memory_dir", None) else default_memory_dir()
    return StdlibBackend(root=root)


# ------------------------------------------------------------------
# Command handlers
# ------------------------------------------------------------------


def cmd_add(args) -> int:
    backend = _get_backend(args)
    try:
        entry = backend.add(
            args.slug,
            body=args.body,
            title=args.title,
            type=args.type,
            tags=args.tags.split(",") if args.tags else None,
            from_file=args.from_file,
        )
        print(f"✅ Added: {entry.slug}  ({entry.size_chars} chars, {len(entry.tags)} tags, {entry.path})")
        return 0
    except FileExistsError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


def cmd_get(args) -> int:
    backend = _get_backend(args)
    entry = backend.get(args.slug)
    if entry is None:
        print(f"Not found: {args.slug}", file=sys.stderr)
        return 1
    if args.frontmatter_only:
        print(f"slug:    {entry.slug}")
        print(f"title:   {entry.title}")
        print(f"type:    {entry.type}")
        print(f"tags:    {','.join(entry.tags)}")
        print(f"updated: {entry.updated.isoformat()}")
        print(f"chars:   {entry.size_chars}")
        print(f"lines:   {entry.size_lines}")
        print(f"path:    {entry.path}")
    else:
        print(entry.raw, end="")
    return 0


def cmd_list(args) -> int:
    backend = _get_backend(args)
    entries = backend.list(prefix=args.prefix, tag=args.tag)
    if not entries:
        print("(no entries)")
        return 0
    print(f"{'SLUG':<42} {'TYPE':<15} {'TAGS':<25} {'CHARS':>7} {'UPDATED':<17}")
    print("-" * 110)
    for e in entries:
        tags = ",".join(e.tags[:3])
        if len(e.tags) > 3:
            tags += f"+{len(e.tags) - 3}"
        updated = e.updated.strftime("%Y-%m-%d %H:%M")
        slug_display = e.slug[:41] + "…" if len(e.slug) > 42 else e.slug
        print(f"{slug_display:<42} {e.type:<15} {tags:<25} {e.size_chars:>7} {updated:<17}")
    print(f"\nTotal: {len(entries)} entries")
    total_chars = sum(e.size_chars for e in entries)
    print(f"Total size: {total_chars} chars")
    return 0


def cmd_search(args) -> int:
    backend = _get_backend(args)
    try:
        matches = backend.search(args.pattern)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    if not matches:
        print(f"No matches for: {args.pattern!r}")
        return 1
    for entry, line in matches:
        print(f"\n📄 {entry.slug}")
        print(f"   {line}")
    print(f"\n{len(matches)} files matched")
    return 0


def cmd_inject(args) -> int:
    backend = _get_backend(args)
    output = backend.inject(args.slugs)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"✅ Injected {len(args.slugs)} entries to {args.output} ({len(output)} chars)")
    else:
        sys.stdout.write(output)
    return 0


def cmd_rm(args) -> int:
    backend = _get_backend(args)
    if not args.force:
        try:
            entry = backend.get(args.slug)
        except ValueError:
            entry = None
        if entry is None:
            print(f"Not found: {args.slug}", file=sys.stderr)
            return 1
        print(f"Will remove: {args.slug}  ({entry.size_chars} chars)")
        try:
            ans = input("Confirm? [y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans != "y":
            print("Cancelled")
            return 0
    if backend.rm(args.slug):
        print(f"✅ Removed: {args.slug}")
        return 0
    print(f"Not found: {args.slug}", file=sys.stderr)
    return 1


def cmd_mv(args) -> int:
    backend = _get_backend(args)
    try:
        backend.mv(args.old_slug, args.new_slug)
        print(f"✅ Moved: {args.old_slug} → {args.new_slug}")
        return 0
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


def cmd_check(args) -> int:
    backend = _get_backend(args)
    entries = backend.list()
    if not entries:
        print("(no entries)")
        return 0

    total = sum(e.size_chars for e in entries)
    budget = args.budget or 1800

    print(f"Total: {len(entries)} entries, {total} chars")
    if total > budget:
        print(f"⚠️  Exceeds budget ({budget} chars) — consider archiving or moving to external storage")

    # Largest entries
    biggest = sorted(entries, key=lambda e: e.size_chars, reverse=True)[:5]
    print("\nTop 5 largest:")
    for e in biggest:
        print(f"  {e.size_chars:>6} chars  {e.slug}")

    # Stale entries (not updated in 90 days)
    stale = [e for e in entries if (datetime.now() - e.updated).days > 90]
    if stale:
        print(f"\n⚠️  {len(stale)} entries not updated in 90+ days:")
        for e in stale[:5]:
            age = (datetime.now() - e.updated).days
            print(f"  {age:>4}d old  {e.slug}")
        if len(stale) > 5:
            print(f"  ... and {len(stale) - 5} more")
        print("  Run `yflow memory diet` to review")
    return 0


def cmd_diet(args) -> int:
    backend = _get_backend(args)
    entries = backend.list()
    if not entries:
        print("(no entries to review)")
        return 0

    print(f"Memory diet review — {len(entries)} entries")
    print(f"Storage: {backend.root}\n")
    print("Commands: [k]eep [r]emove [a]rchive [s]kip [q]uit\n")

    keep, remove = [], []
    for e in entries:
        age_days = (datetime.now() - e.updated).days
        print(f"📄 {e.slug}")
        print(f"   {e.size_chars} chars, {age_days}d old, type={e.type}, tags={e.tags}")
        try:
            choice = input("   [k/r/a/s/q]? ").strip().lower()
        except EOFError:
            choice = "s"
        if choice == "k":
            keep.append(e)
        elif choice == "r":
            remove.append(e)
        elif choice == "q":
            break
        # 'a' and 's' both skip for now (archive not implemented in v0.5.0)

    print(f"\nKeep: {len(keep)}, Remove: {len(remove)}")
    if remove:
        try:
            ans = input(f"Remove {len(remove)} entries? [y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans == "y":
            for e in remove:
                backend.rm(e.slug)
                print(f"  removed: {e.slug}")
    return 0


# ------------------------------------------------------------------
# Subparser registration
# ------------------------------------------------------------------


def register_memory_parser(subparsers) -> argparse.ArgumentParser:
    """Register `yflow memory` and all its sub-subcommands. Return the memory parser."""
    mem_p = subparsers.add_parser("memory", help="Manage second-tier memory (markdown files, XDG)")
    mem_subs = mem_p.add_subparsers(dest="memory_command", required=True)

    # Common: --memory-dir for all
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--memory-dir", help="Override memory dir (for testing)")

    # add
    p = mem_subs.add_parser("add", parents=[common], help="Add a new memory entry")
    p.add_argument("slug", help="Slug (e.g. 'infra/foo' or 'projects/recognize/plan-status')")
    p.add_argument("--title", help="Title (default: derived from slug)")
    p.add_argument("--type", default="note", help="Type: note | reference | workflow | methodology")
    p.add_argument("--tags", help="Comma-separated tags")
    p.add_argument("--body", help="Markdown body (or use --from-file)")
    p.add_argument("--from-file", help="Read body from file")
    p.set_defaults(func=cmd_add)

    # get
    p = mem_subs.add_parser("get", parents=[common], help="Get a memory entry (full content)")
    p.add_argument("slug")
    p.add_argument("--frontmatter-only", action="store_true", help="Print only metadata")
    p.set_defaults(func=cmd_get)

    # list
    p = mem_subs.add_parser("list", parents=[common], help="List all entries")
    p.add_argument("--prefix", help="Filter by slug prefix (e.g. 'infra/')")
    p.add_argument("--tag", help="Filter by tag")
    p.set_defaults(func=cmd_list)

    # search
    p = mem_subs.add_parser("search", parents=[common], help="Search memory (regex)")
    p.add_argument("pattern")
    p.setDefaults = None  # noqa
    p.set_defaults(func=cmd_search)

    # inject
    p = mem_subs.add_parser("inject", parents=[common], help="Merge entries for LLM context")
    p.add_argument("slugs", nargs="+", help="One or more slugs to merge")
    p.add_argument("--output", "-o", help="Write to file instead of stdout")
    p.set_defaults(func=cmd_inject)

    # rm
    p = mem_subs.add_parser("rm", parents=[common], help="Remove an entry (with confirm)")
    p.add_argument("slug")
    p.add_argument("--force", "-f", action="store_true", help="Skip confirm")
    p.set_defaults(func=cmd_rm)

    # mv
    p = mem_subs.add_parser("mv", parents=[common], help="Rename/move a slug")
    p.add_argument("old_slug")
    p.add_argument("new_slug")
    p.set_defaults(func=cmd_mv)

    # check
    p = mem_subs.add_parser("check", parents=[common], help="Validate budget + staleness")
    p.add_argument("--budget", type=int, default=1800, help="Char budget (default 1800)")
    p.set_defaults(func=cmd_check)

    # diet
    p = mem_subs.add_parser("diet", parents=[common], help="Interactive review of all entries")
    p.set_defaults(func=cmd_diet)

    return mem_p


def dispatch_memory(args) -> int:
    """Dispatch `yflow memory <subcmd>` to the right handler."""
    return args.func(args)
