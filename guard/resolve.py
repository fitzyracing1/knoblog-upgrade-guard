"""Map a package to its source repo and a version to a git tag."""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request

GH = re.compile(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?].*)?$")


def _get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "knoblog-upgrade-guard"}), timeout=20) as r:
        return json.load(r)


def _gh(url: str | None) -> str | None:
    m = GH.search(url or "")
    return f"https://github.com/{m.group(1)}/{m.group(2)}" if m else None


def source_repo(name: str, ecosystem: str, overrides: dict) -> str | None:
    if name in overrides and overrides[name].get("repo"):
        return overrides[name]["repo"]
    try:
        if ecosystem == "pypi":
            info = _get(f"https://pypi.org/pypi/{name}/json")["info"]
            urls = list((info.get("project_urls") or {}).items())
            urls.sort(key=lambda kv: 0 if re.search(r"source|code|repo", kv[0], re.I) else 1)
            for _, u in urls + [("home", info.get("home_page"))]:
                if _gh(u):
                    return _gh(u)
        elif ecosystem == "npm":
            doc = _get(f"https://registry.npmjs.org/{name.replace('/', '%2F')}/latest")
            repo = doc.get("repository")
            return _gh(repo.get("url") if isinstance(repo, dict) else repo)
    except Exception:
        return None
    return None


def remote_tags(repo: str) -> list[str]:
    out = subprocess.run(["git", "ls-remote", "--tags", "--refs", repo], capture_output=True, text=True, check=False).stdout
    return [l.split("refs/tags/", 1)[1] for l in out.splitlines() if "refs/tags/" in l]


def find_tag(version: str, tags: list[str], name: str = "", template: str | None = None) -> str | None:
    cands = [template.format(version=version, name=name)] if template else []
    short = name.split("/")[-1]
    cands += [f"v{version}", version, f"{name}@{version}", f"{short}-{version}", f"{short}-v{version}",
              f"release-{version}", f"{name}-{version}", f"{version.replace('.', '_')}"]
    s = set(tags)
    for c in cands:
        if c in s:
            return c
    return None
