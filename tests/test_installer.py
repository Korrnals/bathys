"""Unit tests for bathys.installer: entry formats, path helpers, backups,
and the install() end-to-end cycle against tmp harness configs.

Safety: no test touches the real home directory. `_HARNESS_TARGETS` is
replaced wholesale with tmp paths via `mock.patch.dict(..., clear=True)`
(the `clear=True` matters: without it the real `~/.zcode` target leaks
into the loop), and `_HOME` / `Path.cwd()` are patched wherever
install() reads them (the --with-agent destinations).

Output assertions use ASCII markers ([OK], [=], [SKIP], [DRY]) rather
than Russian phrases, per the installer's printing convention.

Known issue (documented, not fixed here): the --with-agent source is
resolved as `_PKG_DIR.parent / "agents" / "bathys-researcher.md"`, which
is `src/agents/...` under an editable install and `site-packages/agents/...`
in a wheel — neither exists, so a real run raises FileNotFoundError. The
copy mechanics are therefore tested against a fixture repo layout with
`_PKG_DIR` patched; the repo-asset guard below pins the real file.
"""

import contextlib
import datetime
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bathys import installer

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_MD = REPO_ROOT / "agents" / "bathys-researcher.md"


class InstallerTmpTest(unittest.TestCase):
    """Base: tmp sandbox plus safe _HARNESS_TARGETS/_HOME replacement."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)

    def set_targets(self, **targets):
        """Replace the WHOLE harness registry: patch every source the
        installer consults (_HARNESS_TARGETS, cline family, yaml family)."""
        cline = {n: t for n, t in targets.items() if t[2] == "cline"}
        yaml = {n: t for n, t in targets.items() if t[2] in ("goose", "hermes")}
        rest = {n: t for n, t in targets.items()
                if n not in cline and n not in yaml}
        self._clines = cline
        self._yamls = yaml
        ctx = mock.patch.dict(installer._HARNESS_TARGETS, rest, clear=True)
        ctx.start()
        self.addCleanup(ctx.stop)
        if cline:
            c = mock.patch.object(installer, "_cline_targets", return_value=cline)
            c.start(); self.addCleanup(c.stop)
        if yaml:
            y = mock.patch.object(installer, "_yaml_targets", return_value=yaml)
            y.start(); self.addCleanup(y.stop)

    def patch_home(self):
        """Point installer._HOME at the sandbox (agent destination)."""
        ctx = mock.patch.object(installer, "_HOME", self.tmp)
        ctx.start()
        self.addCleanup(ctx.stop)

    def patch_cwd(self):
        """Point Path.cwd() at the sandbox (claude-code agent destination)."""
        ctx = mock.patch("pathlib.Path.cwd", return_value=self.tmp)
        ctx.start()
        self.addCleanup(ctx.stop)

    def run_install(self, **kwargs):
        kwargs.setdefault("dry_run", False)
        kwargs.setdefault("print_config", False)
        kwargs.setdefault("with_agent", False)
        kwargs.setdefault("searxng_home", None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = installer.install(**kwargs)
        return rc, out.getvalue()


class ServerEntryTest(unittest.TestCase):
    """_server_entry: per-format shapes and the bathys launcher command."""

    def test_zcode_entry_without_searxng_home(self):
        entry = installer._server_entry("zcode", None)
        self.assertEqual(set(entry), {"type", "command", "args"})
        self.assertEqual(entry["type"], "stdio")
        self.assertEqual(entry["args"], [])
        self.assertNotIn("env", entry)

    def test_zcode_entry_with_searxng_home(self):
        entry = installer._server_entry("zcode", "/x")
        self.assertEqual(set(entry), {"type", "command", "args", "env"})
        self.assertEqual(entry["type"], "stdio")
        self.assertEqual(entry["args"], [])
        self.assertEqual(entry["env"], {"BATHYS_SEARXNG_HOME": "/x"})

    def test_openai_entry_with_searxng_home(self):
        entry = installer._server_entry("openai", "/x")
        self.assertEqual(set(entry), {"command", "env"})
        self.assertEqual(entry["env"], {"BATHYS_SEARXNG_HOME": "/x"})

    def test_openai_entry_without_searxng_home(self):
        entry = installer._server_entry("openai", None)
        self.assertEqual(set(entry), {"command"})
        self.assertNotIn("env", entry)

    def test_command_is_absolute_bathys_launcher(self):
        # The suite runs via the project venv, where the `bathys` console
        # script exists next to sys.executable — hence the absolute path.
        for fmt in ("zcode", "openai"):
            with self.subTest(fmt=fmt):
                cmd = installer._server_entry(fmt, None)["command"]
                self.assertEqual(cmd, installer._bathys_command())
                self.assertTrue(Path(cmd).is_absolute(), cmd)
                self.assertTrue(cmd.endswith("/bathys"), cmd)


class PathHelpersTest(unittest.TestCase):
    """_get_by_path / _ensure_path: dotted navigation over config dicts."""

    def test_get_by_path_reads_existing_nested_dict(self):
        servers = {"mnemos": {"command": "x"}}
        data = {"mcp": {"servers": servers}}
        self.assertEqual(installer._get_by_path(data, "mcp.servers"), servers)

    def test_get_by_path_missing_returns_none(self):
        self.assertIsNone(installer._get_by_path({}, "mcp.servers"))
        self.assertIsNone(installer._get_by_path({"mcp": {}}, "mcp.servers"))

    def test_get_by_path_non_dict_segment_returns_none(self):
        self.assertIsNone(installer._get_by_path({"mcp": "oops"}, "mcp.servers"))

    def test_ensure_path_creates_nested_dicts(self):
        data = {}
        servers = installer._ensure_path(data, "mcp.servers")
        self.assertEqual(data, {"mcp": {"servers": {}}})
        self.assertEqual(servers, {})
        servers["bathys"] = 1
        self.assertEqual(data["mcp"]["servers"]["bathys"], 1)

    def test_ensure_path_returns_existing_subtree(self):
        servers = {"mnemos": {"command": "x"}}
        data = {"mcp": {"servers": servers}}
        self.assertIs(installer._ensure_path(data, "mcp.servers"), servers)


class EntryNeedsUpdateTest(unittest.TestCase):
    """_entry_needs_update: idempotence rules, foreign env tolerance."""

    CMD = "/usr/local/bin/bathys"

    @staticmethod
    def _entry(**over):
        entry = {"command": EntryNeedsUpdateTest.CMD}
        entry.update(over)
        return entry

    def test_identical_entries_need_no_update(self):
        desired = self._entry()
        self.assertFalse(installer._entry_needs_update(dict(desired), desired))
        with_env = self._entry(env={"BATHYS_SEARXNG_HOME": "/x"})
        self.assertFalse(installer._entry_needs_update(dict(with_env), with_env))

    def test_different_command_needs_update(self):
        existing = self._entry(command="/other/bathys")
        self.assertTrue(installer._entry_needs_update(existing, self._entry()))

    def test_different_type_needs_update(self):
        desired = self._entry(type="stdio")
        existing = self._entry(type="sse")
        self.assertTrue(installer._entry_needs_update(existing, desired))

    def test_env_value_difference_needs_update(self):
        existing = self._entry(env={"BATHYS_SEARXNG_HOME": "/old"})
        desired = self._entry(env={"BATHYS_SEARXNG_HOME": "/new"})
        self.assertTrue(installer._entry_needs_update(existing, desired))

    def test_env_key_missing_in_existing_needs_update(self):
        desired = self._entry(env={"BATHYS_SEARXNG_HOME": "/x"})
        self.assertTrue(installer._entry_needs_update(self._entry(), desired))

    def test_desired_without_env_keeps_foreign_env(self):
        # No env in the desired entry must not count as "remove foreign keys".
        existing = self._entry(env={"BATHYS_SEARXNG_HOME": "/old", "OTHER": "keep"})
        self.assertFalse(installer._entry_needs_update(existing, self._entry()))

    def test_non_dict_existing_needs_update(self):
        desired = self._entry()
        for bad in (None, "bathys", 42, ["x"]):
            with self.subTest(existing=bad):
                self.assertTrue(installer._entry_needs_update(bad, desired))


class BackupTest(InstallerTmpTest):
    """_backup: timestamped copy of an existing file; None otherwise."""

    def test_existing_file_backed_up_with_timestamp(self):
        cfg = self.tmp / "config.json"
        cfg.write_text('{"a": 1}', encoding="utf-8")
        bkp = installer._backup(cfg)
        self.assertIsNotNone(bkp)
        self.assertTrue(bkp.is_file())
        self.assertRegex(bkp.name, r"^config\.json\.bathys-backup-\d{8}-\d{6}$")
        stamp = bkp.name.rsplit("-", 1)[-1]
        datetime.datetime.strptime(stamp, "%H%M%S")  # raises on a bogus stamp
        self.assertEqual(bkp.read_bytes(), cfg.read_bytes())
        self.assertTrue(cfg.is_file())  # original kept in place

    def test_missing_file_returns_none(self):
        self.assertIsNone(installer._backup(self.tmp / "nope.json"))
        self.assertEqual(list(self.tmp.iterdir()), [])


class InstallFullCycleTest(InstallerTmpTest):
    """install(): the write path against a live tmp harness config."""

    def _zcode_config(self, payload):
        cfg = self.tmp / "config.json"
        cfg.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.set_targets(zcode=(cfg, "mcp.servers", "zcode"))
        return cfg

    def test_full_cycle_writes_preserves_and_backs_up(self):
        mnemos = {"command": "mnemos-cmd", "env": {"K": "v"}}
        cfg = self._zcode_config({"mcp": {"servers": {"mnemos": mnemos}}})

        rc, out = self.run_install(searxng_home="/x")

        self.assertEqual(rc, 0)
        self.assertIn("[OK]", out)
        data = json.loads(cfg.read_text(encoding="utf-8"))  # still valid JSON
        servers = data["mcp"]["servers"]
        self.assertEqual(set(servers), {"mnemos", "bathys"})
        self.assertEqual(servers["bathys"], installer._server_entry("zcode", "/x"))
        self.assertEqual(servers["mnemos"], mnemos)  # foreign server untouched
        backups = list(self.tmp.glob("config.json.bathys-backup-*"))
        self.assertEqual(len(backups), 1)

    def test_second_run_is_idempotent_noop(self):
        cfg = self._zcode_config({"mcp": {"servers": {"mnemos": {"command": "x"}}}})
        rc1, _ = self.run_install(searxng_home="/x")
        self.assertEqual(rc1, 0)
        before, mtime = cfg.read_bytes(), cfg.stat().st_mtime_ns

        rc2, out2 = self.run_install(searxng_home="/x")

        self.assertEqual(rc2, 0)  # skipped=1 still counts as success
        self.assertIn("[=]", out2)
        self.assertNotIn("[OK]", out2)
        self.assertEqual(cfg.read_bytes(), before)
        self.assertEqual(cfg.stat().st_mtime_ns, mtime)  # no rewrite happened
        self.assertEqual(len(list(self.tmp.glob("*.bathys-backup-*"))), 1)

    def test_install_creates_missing_dotpath(self):
        cfg = self._zcode_config({})

        rc, out = self.run_install()

        self.assertEqual(rc, 0)
        self.assertIn("[OK]", out)
        data = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["mcp"]["servers"]["bathys"],
                         installer._server_entry("zcode", None))
        self.assertEqual(len(list(self.tmp.glob("config.json.bathys-backup-*"))), 1)


class InstallNoTargetsTest(InstallerTmpTest):
    """install(): no live configs -> manual hint, nothing written."""

    def test_no_targets_prints_manual_hint_and_creates_nothing(self):
        self.set_targets(zcode=(self.tmp / "absent.json", "mcp.servers", "zcode"))

        rc, out = self.run_install()

        self.assertEqual(rc, 0)
        self.assertIn("--print-config", out)
        self.assertEqual(list(self.tmp.iterdir()), [])


class InstallDryRunTest(InstallerTmpTest):
    """install(dry_run=True): plan only, file bytes untouched."""

    def test_dry_run_leaves_file_untouched(self):
        cfg = self.tmp / "mcp.json"
        cfg.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        before = cfg.read_bytes()
        self.set_targets(cursor=(cfg, "mcpServers", "openai"))

        rc, out = self.run_install(dry_run=True)

        self.assertEqual(rc, 0)
        self.assertIn("[DRY]", out)
        self.assertEqual(cfg.read_bytes(), before)
        self.assertEqual(list(self.tmp.glob("*.bathys-backup-*")), [])


class InstallPrintConfigTest(InstallerTmpTest):
    """install(print_config=True): both snippets, no per-target records."""

    def test_print_config_emits_all_formats_without_touching_files(self):
        # print_config walks the WHOLE registry: substitute every family so the
        # output is deterministic regardless of the host machine.
        self.set_targets(
            zcode=(self.tmp / "z.json", "mcp.servers", "zcode"),
            **{"claude-code": (self.tmp / "c.json", "mcpServers", "openai"),
               "gemini-cli": (self.tmp / "g.json", "mcpServers", "openai"),
               "windsurf": (self.tmp / "w.json", "mcpServers", "openai"),
               "zed": (self.tmp / "zset.json", "context_servers", "openai"),
               "opencode": (self.tmp / "oc.json", "mcp", "opencode"),
               "goose": (self.tmp / "goose.yaml", "extensions", "goose"),
               "hermes": (self.tmp / "hermes.yaml", "mcp_servers", "hermes"),
               "cline": (self.tmp / "cline.json", "mcpServers", "cline")},
        )

        rc, out = self.run_install(print_config=True, searxng_home="/x")

        self.assertEqual(rc, 0)
        for marker in ("[OK]", "[=]", "[SKIP]", "[DRY]"):
            self.assertNotIn(marker, out)
        # Every harness family is present with its root key spelled out.
        self.assertIn("## zcode", out)          # nested mcp -> servers JSON
        self.assertIn("## claude-code", out)     # mcpServers
        self.assertIn("## gemini-cli", out)      # mcpServers
        self.assertIn("## windsurf", out)        # mcpServers
        self.assertIn("## zed", out)             # context_servers
        self.assertIn("## opencode", out)       # mcp (local command list)
        self.assertIn("## goose", out)          # YAML extensions
        self.assertIn("## hermes", out)          # YAML mcp_servers
        self.assertIn("## cline", out)           # VS Code globalStorage family
        self.assertIn("extensions:\n  bathys:", out)
        self.assertIn("mcp_servers:\n  bathys:", out)
        # zcode snippet nests servers under mcp and is parseable JSON.
        tail = out[out.index("## zcode"):]
        nxt = tail.index("\n\n## ", 1) if "\n\n## " in tail[1:] else len(tail)
        snippet = tail[tail.index("{"):tail.rindex("}", 0, nxt) + 1]
        zcode = json.loads(snippet)
        self.assertIn("servers", zcode.get("mcp", {}))
        self.assertIn("bathys", zcode["mcp"]["servers"])
        # Pi is explicitly routed to the drop-in, not a config file.
        self.assertIn("Pi", out)
        self.assertEqual(list(self.tmp.iterdir()), [])


class InstallBrokenJsonTest(InstallerTmpTest):
    """install(): unreadable config is skipped, never crashes the run."""

    def test_broken_json_skipped_while_alive_target_updated(self):
        bad = self.tmp / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        bad_before = bad.read_bytes()
        good = self.tmp / "good.json"
        good.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        self.set_targets(cursor=(good, "mcpServers", "openai"),
                         broken=(bad, "mcpServers", "openai"))

        rc, out = self.run_install()

        self.assertEqual(rc, 0)  # one live update outweighs one skip
        self.assertIn("[SKIP]", out)
        self.assertIn("[OK]", out)
        self.assertEqual(bad.read_bytes(), bad_before)  # garbage left as-is
        self.assertEqual(list(self.tmp.glob("bad.json.bathys-backup-*")), [])
        data = json.loads(good.read_text(encoding="utf-8"))
        self.assertIn("bathys", data["mcpServers"])

    def test_only_broken_json_fails_with_exit_1(self):
        bad = self.tmp / "bad.json"
        bad.write_text("garbage", encoding="utf-8")
        self.set_targets(cursor=(bad, "mcpServers", "openai"))

        rc, out = self.run_install()

        # Actual behaviour, fixed as-is: nothing updated and nothing
        # skipped -> install reports total failure with exit code 1.
        self.assertEqual(rc, 1)
        self.assertIn("[SKIP]", out)
        self.assertEqual(bad.read_text(encoding="utf-8"), "garbage")


class InstallWithAgentTest(InstallerTmpTest):
    """install(with_agent=True): researcher profile copy into ~/.zcode/agents."""

    def setUp(self):
        super().setUp()
        # Fixture mirrors the REAL package layout the resolver expects:
        # <repo>/src/bathys (package) + <repo>/agents/bathys-researcher.md.
        repo = self.tmp / "repo"
        pkg = repo / "src" / "bathys"
        pkg.mkdir(parents=True)
        self.agent_src = repo / "agents" / "bathys-researcher.md"
        self.agent_src.parent.mkdir(parents=True)
        self.agent_src.write_text("# bathys researcher profile\n", encoding="utf-8")
        ctx = mock.patch.object(installer, "_PKG_DIR", pkg)
        ctx.start()
        self.addCleanup(ctx.stop)

    def test_repo_ships_researcher_agent_asset(self):
        # Guard, not a mock: the real repo must keep shipping the source
        # file (the installer resolves it next to the package dir).
        self.assertTrue(AGENT_MD.is_file(), f"missing repo asset: {AGENT_MD}")

    def test_with_agent_copies_researcher_into_zcode_agents(self):
        cfg = self.tmp / "config.json"
        cfg.write_text(json.dumps({"mcp": {"servers": {}}}), encoding="utf-8")
        self.set_targets(zcode=(cfg, "mcp.servers", "zcode"))
        self.patch_home()
        self.patch_cwd()

        rc, out = self.run_install(with_agent=True)

        self.assertEqual(rc, 0)
        self.assertIn("[OK]", out)
        dst = self.tmp / ".zcode" / "agents" / "bathys-researcher.md"
        self.assertTrue(dst.is_file())
        self.assertEqual(dst.read_bytes(), self.agent_src.read_bytes())
        # claude-code destination must stay untouched in this layout.
        self.assertFalse((self.tmp / ".claude").exists())

    def test_with_agent_dry_run_prints_plan_without_copying(self):
        cfg = self.tmp / "config.json"
        cfg.write_text(json.dumps({"mcp": {"servers": {}}}), encoding="utf-8")
        self.set_targets(zcode=(cfg, "mcp.servers", "zcode"))
        self.patch_home()
        self.patch_cwd()

        rc, out = self.run_install(dry_run=True, with_agent=True)

        self.assertEqual(rc, 0)
        self.assertIn("[DRY]", out)
        self.assertIn(str(self.tmp / ".zcode" / "agents"), out)
        self.assertFalse((self.tmp / ".zcode").exists())  # nothing created


if __name__ == "__main__":
    unittest.main()