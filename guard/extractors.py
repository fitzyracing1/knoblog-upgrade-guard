"""Extra extractors registered into knoblog at runtime: function/keyword defaults in Python and JS/TS.

knoblog core reads constants; for library upgrades the knobs that bite are usually keyword defaults
(`def request(..., timeout=5.0)`), dataclass/class attributes and JS `defaults = { timeout: 0 }` objects.
"""
from __future__ import annotations

import ast
import re

from knoblog import extractors as KX

LITERAL_NODES = (ast.Constant, ast.Tuple, ast.List, ast.UnaryOp, ast.Dict, ast.Set)


def _lit(node) -> str | None:
    if not isinstance(node, LITERAL_NODES):
        return None
    try:
        ast.literal_eval(node)
    except Exception:
        return None
    s = ast.unparse(node)
    return s if len(s) <= 120 else None


def python_defaults(path: str, text: str) -> dict[str, dict]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    out: list[tuple[str, dict]] = []

    def visit(body, prefix: str):
        for n in body:
            if isinstance(n, ast.ClassDef) and not n.name.startswith("_"):
                visit(n.body, f"{prefix}{n.name}.")
                for st in n.body:  # class attributes / dataclass fields with literal defaults
                    tgt = st.target if isinstance(st, ast.AnnAssign) else (st.targets[0] if isinstance(st, ast.Assign) and len(st.targets) == 1 else None)
                    if isinstance(tgt, ast.Name) and not tgt.id.startswith("_") and getattr(st, "value", None) is not None:
                        v = _lit(st.value)
                        if v is not None:
                            out.append((f"{prefix}{n.name}.{tgt.id}", KX._rec(v)))
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and (not n.name.startswith("_") or n.name == "__init__"):
                a = n.args
                pos = a.posonlyargs + a.args
                pairs = list(zip(pos[len(pos) - len(a.defaults):], a.defaults)) + [(k, d) for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
                fname = prefix[:-1] if n.name == "__init__" and prefix else f"{prefix}{n.name}"
                for arg, d in pairs:
                    v = _lit(d)
                    if v is not None and not arg.arg.startswith("_"):
                        out.append((f"{fname}({arg.arg})", KX._rec(v)))
    visit(tree.body, "")
    return KX._dedupe(out)


_JS_LIT = r"""(-?\d[\d_.]*(?:e[-+]?\d+)?(?:\s*[*+]\s*\d[\d_.]*)*|true|false|null|undefined|'[^'\n]{0,80}'|"[^"\n]{0,80}"|`[^`$\n]{0,80}`|\[(?:\s*(?:'[^'\n]*'|"[^"\n]*"|-?\d[\d.]*|true|false)\s*,?)*\s*\])"""
_JS_CONST = re.compile(rf"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::\s*[\w<>\[\]| ]+)?=\s*{_JS_LIT}\s*;?\s*(?://.*)?$")
_JS_OBJ_START = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)?\s*((?:[A-Za-z_$][\w$.]*)?(?:[Dd]efaults?|DEFAULTS?|[Cc]onfig|[Oo]ptions)\w*)\s*(?::[^=]+)?=\s*(?:Object\.freeze\()?\{\s*$")
_JS_KV = re.compile(rf"^\s*['\"]?([A-Za-z_$][\w$-]*)['\"]?\s*:\s*{_JS_LIT}\s*,?\s*(?://.*)?$")
_JS_NEST = re.compile(r"^\s*['\"]?([A-Za-z_$][\w$-]*)['\"]?\s*:\s*\{\s*$")


def js_defaults(path: str, text: str) -> dict[str, dict]:
    """`export const defaultConfig = Object.freeze({ a: 1, nested: { b: 'x' } })` -> defaultConfig.a, defaultConfig.nested.b."""
    out, stack, skip = [], [], 0
    for line in text.splitlines():
        code = re.sub(r"//.*$", "", line)
        if stack:
            if skip:  # inside a non-literal block (function body, array of objects...)
                skip += code.count("{") + code.count("[") - code.count("}") - code.count("]")
                continue
            m = _JS_NEST.match(code)
            if m:
                stack.append(m.group(1))
                continue
            m = _JS_KV.match(code)
            if m:
                out.append((".".join(stack + [m.group(1)]), KX._rec(m.group(2))))
                continue
            opened = code.count("{") + code.count("[") - code.count("}") - code.count("]")
            if opened > 0:
                skip = opened
                continue
            if re.match(r"^\s*[}\]]", code):
                stack.pop()
            continue
        m = _JS_OBJ_START.match(code)
        if m:
            stack = [m.group(1)]
            continue
        m = _JS_CONST.match(code)
        if m and (m.group(1).isupper() or re.search(r"default|timeout|max|min|limit|retr|size", m.group(1), re.I)):
            out.append((m.group(1), KX._rec(m.group(2))))
    return KX._dedupe(out)


def register() -> None:
    KX.REGISTRY.setdefault("python_defaults", python_defaults)
    KX.REGISTRY.setdefault("js_defaults", js_defaults)


ECOSYSTEM_EXTRACTORS = {
    "pypi": [{"use": "python_defaults", "paths": ["**/*.py"]}, {"use": "python_const", "paths": ["**/*.py"]},
             {"use": "auto", "paths": ["**/*.yaml", "**/*.yml", "**/*.json", "**/*.toml"], "exclude": ["*"]}],
    "npm": [{"use": "js_defaults", "paths": ["**/*.js", "**/*.mjs", "**/*.cjs", "**/*.ts"]}],
    "ros": [{"use": "auto"}],
}
INFRA_EXCLUDE = ["docker/**", "**/docker/**", "extra/**", "scripts/**", "tools/**", "ci/**", "bin/**", "**/*.d.ts",
                 "appveyor.yml", "azure-pipelines.yml", "*.yml", "*.yaml", "*.json", "*.toml", "**/typings/**", "**/types/**"]
