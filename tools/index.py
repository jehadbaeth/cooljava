#!/usr/bin/env python3
"""Rebuild the index in README.md and lint the collection.

  python3 tools/index.py           # rewrite the block between the index markers in README.md
  python3 tools/index.py --check   # only lint: header format, broken relative links, dashes

The index is generated from each doc's own header (title, hook, Since, Verdict), so the
docs are the single source of truth.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
START, END = "<!-- index:start -->", "<!-- index:end -->"

CATEGORIES = {
    "01-functional": "Functional Programming",
    "02-patterns": "Design Patterns, Modernized",
    "03-build-it-yourself": "Build It Yourself",
    "04-generics": "Generics and Type System Wizardry",
    "05-modern-language": "Modern Language Features",
    "06-hidden-corners": "Hidden Corners and Party Tricks",
    "07-puzzlers": "Puzzlers and Gotchas",
    "08-streams-collections": "Streams and Collections",
    "09-concurrency": "Concurrency",
    "10-jvm-performance": "JVM, Reflection and Performance",
    "11-jdk-gems": "JDK Gems",
}
BLURBS = {
    "01-functional": "Monads, trampolines, lenses and friends, in plain Java with no libraries.",
    "02-patterns": "Classic patterns rebuilt with records, sealed types, enums and lambdas.",
    "03-build-it-yourself": "Small, honest implementations of things you usually pull in as a dependency.",
    "04-generics": "Making javac do your bug hunting: phantom types, type tokens, wildcards and worse.",
    "05-modern-language": "What Java 16 to 27 added to the language, and the tricks it enables.",
    "06-hidden-corners": "Legal, surprising, occasionally horrifying. Mostly for fun.",
    "07-puzzlers": "Guess the output, then find out why you were wrong.",
    "08-streams-collections": "Collectors, gatherers, spliterators and the map methods nobody reads about.",
    "09-concurrency": "Virtual threads, structured concurrency, lock-free code and memory model traps.",
    "10-jvm-performance": "Reflection at full speed, bytecode, native calls, flight recorder and bit tricks.",
    "11-jdk-gems": "Batteries you already have: HTTP, time, regex, processes, zip, crypto.",
}

H1 = re.compile(r"^# (\d{3}) · (.+)$")
BADGE = re.compile(
    r"^\*\*Since:\*\* Java (?P<since>\d+)(?P<since_note> \([^)]*\))? · \*\*Category:\*\* \[(?P<cat>[^\]]+)\]\(\.\./README\.md#(?P<anchor>[a-z0-9-]+)\) · "
    r"\*\*Level:\*\* (?P<level>Beginner|Intermediate|Advanced) · \*\*Verdict:\*\* (?P<verdict>✅ Production|⚠️ Situational|🧪 Party trick)$"
)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def anchor(title):
    return re.sub(r"[^a-z0-9 -]", "", title.lower()).replace(" ", "-")


def parse_doc(path):
    lines = path.read_text().split("\n")
    problems = []
    m = H1.match(lines[0]) if lines else None
    if not m:
        return None, [f"{path.name}: first line must be '# NNN · Title'"]
    doc = {"id": m.group(1), "title": m.group(2).strip(), "path": path}
    if not path.name.startswith(doc["id"] + "-"):
        problems.append(f"{path.name}: id in title ({doc['id']}) does not match file name")
    hook = next((l for l in lines[1:6] if l.startswith("> ")), None)
    if not hook:
        problems.append(f"{path.name}: missing '> hook' line under the title")
    doc["hook"] = hook[2:].strip() if hook else ""
    badge = next((BADGE.match(l) for l in lines[1:10] if l.startswith("**Since:**")), None)
    if not badge:
        problems.append(f"{path.name}: badge line missing or malformed")
        return doc, problems
    doc.update(badge.groupdict())
    expected = CATEGORIES.get(path.parent.name)
    if badge["cat"] != expected or badge["anchor"] != anchor(expected or ""):
        problems.append(f"{path.name}: category should be [{expected}](../README.md#{anchor(expected or '')})")
    return doc, problems


def lint(paths):
    problems = []
    for p in paths + [README]:
        if not p.exists():
            continue
        text = p.read_text()
        in_fence = False
        for i, line in enumerate(text.split("\n"), 1):
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if "—" in line or "–" in line:
                problems.append(f"{p.relative_to(ROOT)}:{i}: em or en dash")
            if in_fence:
                continue
            line = re.sub(r"`[^`]*`", "``", line)  # links inside inline code are not links
            for target in LINK.findall(line):
                if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                    continue
                file_part = target.split("#", 1)[0]
                if file_part and not (p.parent / file_part).resolve().exists():
                    problems.append(f"{p.relative_to(ROOT)}:{i}: broken link {target}")
    return problems


def render(docs):
    out = []
    by_cat = {}
    for d in docs:
        by_cat.setdefault(d["path"].parent.name, []).append(d)
    verdicts = Counter(d.get("verdict", "?") for d in docs)
    out.append(
        f"**{len(docs)} documents** · "
        + " · ".join(f"{v} {verdicts[v]}" for v in ("✅ Production", "⚠️ Situational", "🧪 Party trick"))
    )
    out.append("")
    out.append("| Category | Docs |")
    out.append("|---|---|")
    for cat, title in CATEGORIES.items():
        ds = by_cat.get(cat, [])
        if ds:
            out.append(f"| [{title}](#{anchor(title)}) | {ds[0]['id']} to {ds[-1]['id']} ({len(ds)}) |")
    for cat, title in CATEGORIES.items():
        ds = by_cat.get(cat, [])
        if not ds:
            continue
        out += ["", f"## {title}", "", f"*{BLURBS[cat]}*", ""]
        out.append("| # | Topic | Java | Verdict |")
        out.append("|---|---|---|---|")
        for d in ds:
            rel = d["path"].relative_to(ROOT).as_posix()
            note = d.get("since_note") or ""
            since = d.get("since", "?") + (
                " (preview)" if note.startswith(" (preview") else " (incubator)" if note.startswith(" (incubator") else "+"
            )
            hook = d["hook"].replace("|", "\\|")
            out.append(
                f"| {d['id']} | **[{d['title']}]({rel})**<br>{hook} | {since} | {d.get('verdict', '?')} |"
            )
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    paths = sorted(ROOT.glob("[0-9][0-9]-*/[0-9][0-9][0-9]-*.md"))
    docs, problems = [], []
    for p in paths:
        d, probs = parse_doc(p)
        problems += probs
        if d:
            docs.append(d)
    ids = Counter(d["id"] for d in docs)
    problems += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    problems += lint(paths)
    if not a.check:
        text = README.read_text()
        if START not in text or END not in text:
            sys.exit("README.md has no index markers")
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        README.write_text(head + START + "\n" + render(docs) + "\n" + END + tail)
        print(f"index rebuilt with {len(docs)} docs")
    for p in problems:
        print("  " + p)
    print(f"{len(paths)} docs, {len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
