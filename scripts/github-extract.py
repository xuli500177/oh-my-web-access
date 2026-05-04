#!/usr/bin/env python3
"""
GitHub Repository Extract — clone repo, return directory tree + README.

Usage:
  github-extract.py https://github.com/owner/repo
  github-extract.py https://github.com/owner/repo --depth 3
  github-extract.py https://github.com/owner/repo --max-files 500
  github-extract.py https://github.com/owner/repo --save /tmp/tree.md
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

GITHUB_RE = re.compile(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/|$)")


def main():
    parser = argparse.ArgumentParser(description="Extract GitHub repo tree and README")
    parser.add_argument("url", help="GitHub repository URL")
    parser.add_argument("--depth", type=int, default=1, help="Git clone depth")
    parser.add_argument("--max-files", type=int, default=300, help="Max files in tree")
    parser.add_argument("--save", help="Save output to file")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    m = GITHUB_RE.search(args.url)
    if not m:
        print("Error: Not a GitHub URL", file=sys.stderr)
        sys.exit(1)

    owner, repo = m.group(1), m.group(2)
    clone_url = f"https://github.com/{owner}/{repo}"

    with tempfile.TemporaryDirectory(prefix="gh-extract-") as tmpdir:
        clone_path = os.path.join(tmpdir, repo)

        print(f"[github] Cloning {clone_url} (depth={args.depth})...", file=sys.stderr)
        result = subprocess.run(
            ["git", "clone", f"--depth={args.depth}", "--quiet", clone_url, clone_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"Error: Clone failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)

        # Directory tree
        tree_lines = []
        for root, dirs, files in os.walk(clone_path):
            # Skip .git
            dirs[:] = [d for d in dirs if d != ".git"]
            rel_root = os.path.relpath(root, clone_path)
            if rel_root == ".":
                rel_root = ""
            for name in sorted(dirs + files):
                rel_path = os.path.join(rel_root, name) if rel_root else name
                tree_lines.append(rel_path)
                if len(tree_lines) >= args.max_files:
                    break
            if len(tree_lines) >= args.max_files:
                break
        tree_lines.sort()

        # README
        readme = ""
        for name in ["README.md", "README.rst", "README.txt", "README"]:
            p = os.path.join(clone_path, name)
            if os.path.exists(p):
                with open(p, "r", errors="replace") as f:
                    readme = f.read()
                break

        # Package metadata
        pkg_info = {}
        pkg_json = os.path.join(clone_path, "package.json")
        if os.path.exists(pkg_json):
            try:
                with open(pkg_json) as f:
                    pj = json.load(f)
                pkg_info = {
                    "name": pj.get("name", ""),
                    "description": pj.get("description", ""),
                    "version": pj.get("version", ""),
                }
            except Exception:
                pass

    # Build output
    tree_text = "\n".join(tree_lines)
    if len(tree_lines) >= args.max_files:
        tree_text += f"\n... (truncated at {args.max_files} files)"

    output = f"# {owner}/{repo}\n\n"
    output += f"URL: {clone_url}\n\n"
    output += f"## Directory Tree\n\n```\n{tree_text}\n```\n\n"

    if pkg_info:
        output += f"## Package\n\n"
        if pkg_info.get("name"):
            output += f"- Name: {pkg_info['name']}\n"
        if pkg_info.get("description"):
            output += f"- Description: {pkg_info['description']}\n"
        if pkg_info.get("version"):
            output += f"- Version: {pkg_info['version']}\n"
        output += "\n"

    if readme:
        output += f"## README\n\n{readme}\n"

    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(output, encoding="utf-8")
        print(f"[saved] {args.save}", file=sys.stderr)

    if args.json:
        print(json.dumps({
            "owner": owner,
            "repo": repo,
            "url": clone_url,
            "files": tree_lines,
            "readme": readme,
            "package": pkg_info,
        }, ensure_ascii=False, indent=2))
    else:
        print(output)


if __name__ == "__main__":
    main()
