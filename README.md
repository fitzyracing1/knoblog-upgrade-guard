# knoblog-upgrade-guard

**Know which defaults changed before you merge a dependency bump.**

Dependabot and Renovate tell you that `gunicorn` went from `20.1.0` to `23.0.0`. They don't tell you that
`forwarded_allow_ips` now defaults to `'127.0.0.1,::1'` where it used to be `'127.0.0.1'`. This Action finds every bumped
dependency in a pull request, diffs the **old tag against the new tag** of that dependency's own source repo with
[knoblog](https://github.com/fitzyracing1/knoblog), and posts one PR comment listing the changed defaults (old,
new, Δ%, file link). It updates that same comment on later pushes.

**Live demos:** [pip bump: gunicorn/celery/httpx (knobs-guard-demo#1)](https://github.com/fitzyracing1/knobs-guard-demo/pull/1) · [npm bump: next 15.0 → 15.1 (knobs-guard-demo#2)](https://github.com/fitzyracing1/knobs-guard-demo/pull/2)

## Usage

```yaml
# .github/workflows/knobs-upgrade-guard.yml
name: knobs upgrade guard
on:
  pull_request:
    paths: ['**/requirements*.txt', '**/pyproject.toml', '**/package.json', '**/package.xml']
permissions:
  contents: read
  pull-requests: write
jobs:
  knobs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - uses: fitzyracing1/knoblog-upgrade-guard@v0
```

| Input | Default | |
|---|---|---|
| `config` | `.github/knobs.yml` | optional overrides, see [examples/knobs.yml](examples/knobs.yml) |
| `comment` | `true` | post/update the PR comment |
| `fail-on-change` | `false` | fail the check if any default changed |
| `knoblog-version` | `knoblog>=0.1.1` | pip spec |

Outputs: `bumps` and `changed`. The full result goes to the job summary as well.

## What is detected

| Manifest | Bumps read from | Source repo resolved from |
|---|---|---|
| `requirements*.txt` / `.in` | `==`, `~=`, `>=` pins | PyPI `project_urls` |
| `pyproject.toml` | PEP 621 deps and optional deps, Poetry | PyPI |
| `package.json` | dependencies, devDependencies, peer, optional (`^1.2.3` etc.) | npm `repository` |
| `package.xml` (ROS) | `version_eq` / `version_gte` pins | `dependencies.<pkg>.repo` in knobs.yml |

Tags are matched as `v1.2.3`, `1.2.3`, `pkg@1.2.3`, `pkg-1.2.3`, `release-1.2.3`, or a `tag:` template you set.

What counts as a default:

- **Python**: keyword/positional defaults on public functions and constructors (`Client(timeout)`), class and
  dataclass attributes with literal values, and UPPER_CASE module constants.
- **JS/TS**: `defaults`/`config`/`options` object literals, and UPPER_CASE or timeout/limit-style constants.
- **ROS 2 / PX4 / ArduPilot / YAML / JSON / TOML / C/C++**: everything knoblog core extracts.

Tests, docs, examples, CI config and packaging metadata are excluded by default.

**ROS / rosdep:** most `package.xml` files don't pin versions, and rosdep keys resolve to distro packages, not tags.
For ROS, map the packages you care about in `.github/knobs.yml` (repo, tag template, paths). The guard then diffs
those whenever the pinned version or `repos` ref changes.

## Run locally

```bash
pip install knoblog
git clone https://github.com/fitzyracing1/knoblog-upgrade-guard && export PYTHONPATH=$PWD/knoblog-upgrade-guard
cd your-repo && python -m guard --base origin/main --head HEAD   # writes knobs.md + knobs.json
```

MIT licensed. Part of [knobs](https://github.com/fitzyracing1/knobs).

## Plans

This project is free, and its license stays as is. Support it through [GitHub Sponsors](https://github.com/sponsors/fitzyracing1):

- **Free**: use the code, community support.
- **Pro ($49/month)**: priority issues and support.
- **Team ($199/month)**: priority support for your team plus early access.
