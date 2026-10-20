import os, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from guard import deps, extractors, main, resolve


class Deps(unittest.TestCase):
    def test_parsers(self):
        self.assertEqual(deps.parse_requirements("Requests==2.31.0\nfoo>=1.2 # x\nbar\n"), {"requests": "2.31.0", "foo": "1.2"})
        self.assertEqual(deps.parse_package_json('{"dependencies":{"axios":"^1.6.0","x":"latest"}}'), {"axios": "1.6.0"})
        self.assertEqual(deps.parse_pyproject('[project]\ndependencies=["gunicorn==22.0.0"]'), {"gunicorn": "22.0.0"})
        self.assertEqual(deps.parse_package_xml('<depend version_gte="1.2.0">rclcpp</depend><depend>std_msgs</depend>'), {"rclcpp": "1.2.0"})

    def test_bumps_in_git(self):
        d = tempfile.mkdtemp()
        g = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d, check=True, capture_output=True)
        g("init", "-q")
        open(os.path.join(d, "requirements.txt"), "w").write("gunicorn==20.1.0\nflask==3.0.0\n")
        g("add", "."); g("commit", "-qm", "a")
        open(os.path.join(d, "requirements.txt"), "w").write("gunicorn==23.0.0\nflask==3.0.0\n")
        g("commit", "-qam", "b")
        self.assertEqual(deps.bumps("HEAD~1", "HEAD", d), [{"name": "gunicorn", "ecosystem": "pypi", "old": "20.1.0", "new": "23.0.0", "manifest": "requirements.txt"}])


class Extract(unittest.TestCase):
    def test_python_defaults(self):
        src = "class Client:\n    retries = 3\n    def __init__(self, timeout=5.0, *, verify=True):\n        pass\n\ndef get(url, stream=False, _x=1):\n    pass\n"
        out = {k: v["value"] for k, v in extractors.python_defaults("a.py", src).items()}
        self.assertEqual(out, {"Client.retries": "3", "Client(timeout)": "5.0", "Client(verify)": "True", "get(stream)": "False"})

    def test_js_defaults(self):
        src = "const defaults = {\n  timeout: 0,\n  maxRedirects: 21,\n  headers: {\n    a: 1\n  }\n};\nexport const MAX_RETRIES = 3;\n"
        out = {k: v["value"] for k, v in extractors.js_defaults("d.js", src).items()}
        self.assertEqual(out, {"defaults.timeout": "0", "defaults.maxRedirects": "21", "MAX_RETRIES": "3"})


class Resolve(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(resolve.find_tag("1.2.0", ["1.2.0", "v1.1"]), "1.2.0")
        self.assertEqual(resolve.find_tag("1.2.0", ["v1.2.0"]), "v1.2.0")
        self.assertEqual(resolve.find_tag("1.2.0", ["pkg@1.2.0"], "pkg"), "pkg@1.2.0")
        self.assertIsNone(resolve.find_tag("9.9", ["v1"]))

    def test_render(self):
        md = main.render([{"name": "g", "ecosystem": "pypi", "old": "1", "new": "2", "manifest": "r.txt", "repo": "https://github.com/o/g",
                           "old_tag": "1", "new_tag": "2", "files_scanned": 3, "removed": [],
                           "changed": [{"name": "Cfg(timeout)", "old": "30", "new": "60", "file": "g/c.py", "pct": 1.0, "ratio": 2.0}]}])
        self.assertIn(main.MARKER, md)
        self.assertIn("| `Cfg(timeout)` | `30` | `60` | +100% |", md)


@unittest.skipUnless(os.environ.get("GUARD_NETWORK"), "set GUARD_NETWORK=1 for the live end-to-end test")
class Live(unittest.TestCase):
    def test_gunicorn_forwarded_allow_ips(self):
        r = main.diff_defaults("https://github.com/benoitc/gunicorn", "20.1.0", "23.0.0", {"paths": ["gunicorn/**"]}, tempfile.mkdtemp())
        names = {c["name"]: (c["old"], c["new"]) for c in r["changed"]}
        self.assertEqual(names["ProxyAllowFrom.default"], ("'127.0.0.1'", "'127.0.0.1,::1'"))


if __name__ == "__main__":
    unittest.main()
