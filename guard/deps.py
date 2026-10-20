"""Find dependency version bumps between two revisions of a repo's manifest files."""
from __future__ import annotations

import json
import re
import subprocess
import tomllib

REQ_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(==|===|~=|>=)\s*([0-9][^\s,;#]*)")
PKG_XML = re.compile(r"<(?:build_|exec_|test_)?depend(?:\s+version_(?:eq|gte)=\"([^\"]+)\")?\s*>([^<]+)</")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = REQ_LINE.match(line)
        if m:
            out[norm(m.group(1))] = m.group(3)
    return out


def parse_pyproject(text: str) -> dict[str, str]:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    specs = list(doc.get("project", {}).get("dependencies", []))
    for grp in doc.get("project", {}).get("optional-dependencies", {}).values():
        specs += grp
    out = parse_requirements("\n".join(specs))
    for name, v in doc.get("tool", {}).get("poetry", {}).get("dependencies", {}).items():
        v = v.get("version") if isinstance(v, dict) else v
        m = re.match(r"^[=^~>]*\s*([0-9][\w.]*)", v or "")
        if m and name != "python":
            out[norm(name)] = m.group(1)
    return out


def parse_package_json(text: str) -> dict[str, str]:
    try:
        doc = json.loads(text)
    except ValueError:
        return {}
    out = {}
    for sec in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for name, spec in (doc.get(sec) or {}).items():
            m = re.match(r"^[=^~v>]*\s*(\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?)$", str(spec).strip())
            if m:
                out[name] = m.group(1)
    return out


def parse_package_xml(text: str) -> dict[str, str]:
    """ROS package.xml: only dependencies pinned with version_eq / version_gte carry a version."""
    return {name.strip(): ver for ver, name in PKG_XML.findall(text) if ver}


PARSERS = [
    (re.compile(r"(^|/)requirements[^/]*\.(txt|in)$"), "pypi", parse_requirements),
    (re.compile(r"(^|/)pyproject\.toml$"), "pypi", parse_pyproject),
    (re.compile(r"(^|/)package\.json$"), "npm", parse_package_json),
    (re.compile(r"(^|/)package\.xml$"), "ros", parse_package_xml),
]


def git(args: list[str], cwd: str = ".") -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False).stdout


def bumps(base: str, head: str, cwd: str = ".") -> list[dict]:
    """[{name, ecosystem, old, new, manifest}] for every dependency whose pinned version changed."""
    files = [f for f in git(["diff", "--name-only", base, head], cwd).splitlines() if f]
    out = []
    for f in files:
        for rx, eco, parse in PARSERS:
            if not rx.search(f) or "node_modules/" in f:
                continue
            old = parse(git(["show", f"{base}:{f}"], cwd))
            new = parse(git(["show", f"{head}:{f}"], cwd))
            for name in sorted(set(old) & set(new)):
                if old[name] != new[name]:
                    out.append({"name": name, "ecosystem": eco, "old": old[name], "new": new[name], "manifest": f})
    return out
