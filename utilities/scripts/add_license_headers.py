#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Insert the Amazon MIT-0 license header into first-party source files.

Run from the repo root. Idempotent: files that already carry the copyright line
(or an SPDX identifier) are skipped. The file list comes from `git ls-files`, so
build output (node_modules, cdk.out) is never touched. A shebang or HTML doctype
on line 1 is preserved; the header is inserted directly after it.

Usage:
    python utilities/scripts/add_license_headers.py           # add headers
    python utilities/scripts/add_license_headers.py --check    # CI / pre-commit
"""

import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

HEADER_LINES = [
    "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.",
    "SPDX-License-Identifier: MIT-0",
]

# Comment styles per file kind.
HASH = {
    "suffixes": {".py", ".yaml", ".yml", ".sh"},
    # Dotfiles have an empty suffix, so match config files by name.
    "names": {"Dockerfile", "requirements.txt", ".env.example", "env-erpnext", ".bandit"},
}
# Note: .cedar uses // line comments; handled in render below via SLASH set.
SLASH = {"suffixes": {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".cedar"}}
BLOCK = {"suffixes": {".css"}}
HTML = {"suffixes": {".html"}}

# Never touch these (generated, vendored, or non-source).
SKIP_PREFIXES = ("infra/cdk.out/", "frontend/dist/", "backend/seed/output/")
SKIP_SUBSTRINGS = ("/node_modules/", "/__pycache__/")
# Vendored third-party assets — leave their upstream headers/content alone.
SKIP_EXACT = {
    "frontend/public/vite.svg",
    "frontend/src/assets/react.svg",
}


def render_hash() -> str:
    return "\n".join(f"# {ln}".rstrip() for ln in HEADER_LINES) + "\n"


def render_slash() -> str:
    return "\n".join(f"// {ln}".rstrip() for ln in HEADER_LINES) + "\n"


def render_block() -> str:
    body = "\n".join(f"   {ln}".rstrip() for ln in HEADER_LINES)
    return f"/*\n{body}\n*/\n"


def render_html() -> str:
    return "\n".join(f"<!-- {ln} -->" for ln in HEADER_LINES) + "\n"


def already_headered(text: str) -> bool:
    head = "\n".join(text.splitlines()[:6])
    return "Copyright Amazon.com" in head or "SPDX-License-Identifier" in head


def header_for(path: Path) -> str | None:
    # .cedar is in both HASH["suffixes"] intent and SLASH; Cedar uses //.
    if path.suffix in SLASH["suffixes"]:
        return render_slash()
    if path.suffix in HASH["suffixes"] or path.name in HASH["names"]:
        return render_hash()
    if path.suffix in BLOCK["suffixes"]:
        return render_block()
    if path.suffix in HTML["suffixes"]:
        return render_html()
    return None


def insert(text: str, header: str) -> str:
    lines = text.splitlines(keepends=True)
    if not lines:
        return header
    first = lines[0]
    # Preserve a line-1 directive that must stay first: shebang, HTML doctype,
    # or a Dockerfile `# syntax=` parser directive.
    stripped = first.lstrip().lower()
    if (
        first.startswith("#!")
        or stripped.startswith("<!doctype")
        or stripped.startswith("# syntax=")
    ):
        rest = "".join(lines[1:])
        sep = "" if first.endswith("\n") else "\n"
        return f"{first}{sep}{header}{rest}"
    return f"{header}{text}"


def tracked_source_files() -> list[Path]:
    git = shutil.which("git")
    if git is None:
        raise SystemExit("git not found on PATH; run this from a git checkout")
    out = subprocess.run(  # nosec B603  # nosemgrep: dangerous-subprocess-use-audit
        [git, "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    files = []
    for rel in out:
        if rel in SKIP_EXACT:
            continue
        if rel.startswith(SKIP_PREFIXES) or any(s in rel for s in SKIP_SUBSTRINGS):
            continue
        p = Path(rel)
        if header_for(p) is not None and p.is_file():
            files.append(p)
    return files


def main() -> int:
    check_only = "--check" in sys.argv
    changed = skipped = 0
    missing: list[str] = []
    for path in tracked_source_files():
        text = path.read_text(encoding="utf-8")
        if already_headered(text):
            skipped += 1
            continue
        if check_only:
            missing.append(str(path))
            continue
        header = header_for(path)
        if header is None:  # tracked_source_files() already filters these out
            continue
        path.write_text(insert(text, header), encoding="utf-8")
        changed += 1
    if check_only:
        if missing:
            print("Missing MIT-0 license header in:")
            for m in missing:
                print(f"  {m}")
            print(
                f"\n{len(missing)} file(s). Run: "
                "python utilities/scripts/add_license_headers.py"
            )
            return 1
        print(f"license headers OK ({skipped} files checked)")
        return 0
    print(f"headers added: {changed}, already-present (skipped): {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
