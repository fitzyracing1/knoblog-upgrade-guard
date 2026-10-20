"""Entry point: python -m guard --base SHA --head SHA [--config .github/knobs.yml] [--comment PR_NUMBER]"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

from knoblog import config as C
from knoblog.analyze import CONST_LIKE, analyze_commit
from knoblog.gitio import CommitMeta, run

from . import __version__
from .deps import bumps
from .extractors import ECOSYSTEM_EXTRACTORS, INFRA_EXCLUDE, register
from .resolve import find_tag, remote_tags, source_repo

MARKER = "<!-- knoblog-upgrade-guard -->"
EXTRA_EXCLUDE = ["**/docs/**", "**/doc/**", "**/examples/**", "**/example/**", "**/benchmarks/**", "**/fixtures/**",
                 "**/*.md", "**/*.rst", "**/CHANGELOG*", "**/.github/**", "**/test_*", "**/*_test.*", "**/*.test.*",
                 "**/*.spec.*", "**/__tests__/**", "**/testing/**", "**/dist/**", "**/build/**", "**/*.min.js",
                 "**/package.json", ".*", "**/.*", ".*/**", "**/.*/**", "**/bower.json", "**/composer.json", "**/*.cfg", "**/tox.ini", "**/noxfile.py", "**/setup.py", "**/conftest.py", "**/mkdocs.yml", "**/codecov.yml", "**/pyproject.toml", "**/setup.cfg", "**/*.lock", "**/tsconfig*.json"]


def log(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def load_cfg(path: str | None) -> dict:
    if path and os.path.exists(path):
        return C.parse_text(open(path, encoding="utf-8").read(), path)
    return {}


def diff_defaults(repo: str, old_tag: str, new_tag: str, dep_cfg: dict, cache: str, ecosystem: str = "pypi") -> dict:
    register()
    dest = os.path.join(cache, re.sub(r"[^\w.-]+", "_", repo.split("//")[-1]))
    if not os.path.isdir(dest):
        subprocess.run(["git", "init", "-q", "--bare", dest], check=True)
        run(["remote", "add", "origin", repo], cwd=dest, check=False)
    subprocess.run(["git", "fetch", "-q", "--filter=blob:none", "--depth=1", "origin",
                    f"+refs/tags/{old_tag}:refs/tags/{old_tag}", f"+refs/tags/{new_tag}:refs/tags/{new_tag}"], cwd=dest, check=True)
    old = run(["rev-parse", f"{old_tag}^{{commit}}"], cwd=dest).strip()
    new = run(["rev-parse", f"{new_tag}^{{commit}}"], cwd=dest).strip()
    over = {"watch": {"paths": dep_cfg.get("paths") or ["**"],
                      "exclude": (dep_cfg.get("exclude") or []) + EXTRA_EXCLUDE + (INFRA_EXCLUDE if ecosystem != "ros" else []) + C.load(None, "generic")["watch"]["exclude"]},
            "track_moves": False, "extractors": dep_cfg.get("extractors") or ECOSYSTEM_EXTRACTORS.get(ecosystem, [{"use": "auto"}])}
    cfg = C.load(None, dep_cfg.get("preset") or "generic", over)
    meta = CommitMeta(new, [old], "", "", f"{old_tag}..{new_tag}", "")
    e = analyze_commit(dest, meta, cfg, repo)
    skip = re.compile(dep_cfg.get("ignore_names") or r"(^|\.)(version|__version__|VERSION|desc|doc|short|section|meta|cli|validator|action|nargs|metavar|name|type)$")
    changes = [c for c in e["changes"] if c["kind"] in ("changed", "moved") and c["old"] != c["new"] and not skip.search(c["name"])]
    removed = [c for c in e["changes"] if c["kind"] == "removed" and c["extractor"] not in CONST_LIKE and not skip.search(c["name"])]
    return {"old_sha": old, "new_sha": new, "files_scanned": e["stats"]["files"], "changed": changes, "removed": removed}


def fmt_pct(c: dict) -> str:
    p = c.get("pct")
    return "" if p is None else f"{p * 100:+.0f}%" if abs(p) < 10 else f"{c['ratio']:.3g}x" if c.get("ratio") else ""


def render(results: list[dict], limit: int = 25) -> str:
    out = [MARKER, "### 🎛️ Changed defaults in bumped dependencies", ""]
    total = sum(len(r.get("changed", [])) for r in results)
    if not results:
        out.append("No pinned dependency bumps detected.")
    for r in results:
        head = f"<b>{r['name']}</b> <code>{r['old']}</code> → <code>{r['new']}</code> ({r['ecosystem']}, <code>{r['manifest']}</code>)"
        if r.get("error"):
            out += [f"- {head}: skipped. {r['error']}", ""]
            continue
        cmp_url = f"{r['repo']}/compare/{r['old_tag']}...{r['new_tag']}"
        ch = r["changed"]
        rm = f", {len(r['removed'])} removed" if r["removed"] else ""
        out.append(f"<details{' open' if ch else ''}><summary>{head}: <b>{len(ch)} changed default{'s' if len(ch) != 1 else ''}</b>"
                   f"{rm}</summary>\n")
        out.append(f"Source: [{r['repo'].split('github.com/')[-1]} {r['old_tag']}...{r['new_tag']}]({cmp_url}) · {r['files_scanned']} changed files scanned\n")
        if ch:
            out += ["| Name | Old | New | Δ | File |", "|---|---|---|---|---|"]
            for c in ch[:limit]:
                cell = lambda v: "`" + str(v).replace("|", "\\|").replace("`", "'")[:60] + "`"
                out.append(f"| {cell(c['name'])} | {cell(c['old'])} | {cell(c['new'])} | {fmt_pct(c)} | "
                           f"[{c['file'].split('/')[-1]}]({r['repo']}/blob/{r['new_tag']}/{c['file']}) |")
            if len(ch) > limit:
                out.append(f"\n…and {len(ch) - limit} more (see the job summary / `knobs.json` artifact).")
        if r["removed"]:
            out.append("\nRemoved: " + ", ".join(f"`{c['name']}`" for c in r["removed"][:15]) + (" …" if len(r["removed"]) > 15 else ""))
        out += ["", "</details>", ""]
    out.append(f"<sub>{total} changed default(s). Values are read verbatim from the dependency's source by "
               f"[knoblog](https://github.com/fitzyracing1/knoblog) · [knoblog-upgrade-guard](https://github.com/fitzyracing1/knoblog-upgrade-guard) v{__version__}</sub>")
    return "\n".join(out)


def gh_api(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request("https://api.github.com" + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "knoblog-upgrade-guard"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def upsert_comment(repo: str, pr: int, body: str) -> str:
    existing = [c for c in gh_api("GET", f"/repos/{repo}/issues/{pr}/comments?per_page=100") if MARKER in (c.get("body") or "")]
    if existing:
        return gh_api("PATCH", f"/repos/{repo}/issues/comments/{existing[0]['id']}", {"body": body})["html_url"]
    return gh_api("POST", f"/repos/{repo}/issues/{pr}/comments", {"body": body})["html_url"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="knoblog-upgrade-guard")
    p.add_argument("--base", required=True)
    p.add_argument("--head", default="HEAD")
    p.add_argument("--config", default=".github/knobs.yml")
    p.add_argument("--cache-dir", default=os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "knobs-cache"))
    p.add_argument("--out", default="knobs.json")
    p.add_argument("--markdown", default="knobs.md")
    p.add_argument("--comment", type=int, help="PR number to comment on (needs GITHUB_TOKEN and GITHUB_REPOSITORY)")
    p.add_argument("--fail-on-change", action="store_true")
    a = p.parse_args(argv)
    cfg = load_cfg(a.config)
    deps_cfg = cfg.get("dependencies") or {}
    ignore = set(cfg.get("ignore") or [])
    results = []
    for b in bumps(a.base, a.head):
        if b["name"] in ignore:
            continue
        dc = deps_cfg.get(b["name"]) or {}
        r = dict(b)
        repo = source_repo(b["name"], b["ecosystem"], deps_cfg)
        if not repo:
            r["error"] = "no GitHub source repo found (add it under `dependencies:` in .github/knobs.yml)."
            results.append(r); continue
        tags = remote_tags(repo)
        ot, nt = (find_tag(v, tags, b["name"], dc.get("tag")) for v in (b["old"], b["new"]))
        r.update(repo=repo, old_tag=ot, new_tag=nt)
        if not (ot and nt):
            r["error"] = f"no git tag for {b['old'] if not ot else b['new']} in {repo} (set `tag: \"v{{version}}\"` style template)."
            results.append(r); continue
        log(f"[diff] {b['name']} {repo} {ot}..{nt}")
        try:
            r.update(diff_defaults(repo, ot, nt, dc, a.cache_dir, b["ecosystem"]))
        except Exception as exc:
            r["error"] = f"diff failed: {exc}"
        results.append(r)
    md = render(results)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"generator": f"knoblog-upgrade-guard {__version__}", "bumps": results}, f, indent=1, default=str)
    with open(a.markdown, "w", encoding="utf-8") as f:
        f.write(md + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(md + "\n")
    total = sum(len(r.get("changed", [])) for r in results)
    if os.environ.get("GITHUB_OUTPUT"):
        open(os.environ["GITHUB_OUTPUT"], "a").write(f"bumps={len(results)}\nchanged={total}\n")
    print(md)
    if a.comment and results:
        log("[comment] " + upsert_comment(os.environ["GITHUB_REPOSITORY"], a.comment, md))
    return 1 if a.fail_on_change and total else 0
