"""AGF 七维坐标申报：task start 的最小切口（只申报记录，不执法）。 覆盖画像承诺：枚举校验 / 推导直通与多卡冲突取严 / 申报优先于推导 / 维度间约束警告（quality=human 而 decider 不到人）/ CLI+MCP 双入口 / start 证据对新旧任务的兼容。坐标系宪法在 AGF 仓（agf/src/agf/models.py）， 本模块的枚举逐字对齐它——指针而非引擎。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bootstrap  # noqa: F401
from support import git_project, write_project

from ag2c.checks import (
    WARNING_ESCALATION_THRESHOLD,
    _record_warnings_and_find_escalated,
)
from ag2c.config import discover_manifest, load_manifest
from ag2c.model import Manifest
from ag2c.coordinates import (
    CONSERVATIVE_DEFAULTS,
    COORDINATE_ENUMS,
    COORDINATE_FIELDS,
    CONSTRAINT_WARNING_KIND,
    RECONCILIATION_WARNING_KIND,
    constraint_warnings,
    derive_from_cards,
    reconciliation_warnings,
    resolve_coordinates,
    validate_declaration,
)
from ag2c.errors import AG2CError
from ag2c.ledger import append_event
from ag2c.tasks import _start_evidence_valid, start_task

PORTRAIT = (
    "Done looks like: 服务函数返回值变更。Surfaces: verify 通过。"
    "Out of result: 不动其他模块。验证层: 机器验证 tests 套件全绿，输出片段进 finish proof。无加料。"
)


def _project(tmp: str) -> Path:
    """生产拓扑夹具（与 test_tasks.AutoRefreshTests 同款）：enroll 外部存储 + gated policy。"""
    from ag2c.enrollment import enroll_project

    base = Path(tmp)
    root = git_project(base / "proj")
    (root / "src" / "api").mkdir(parents=True)
    (root / "src" / "worker").mkdir(parents=True)
    (root / "src" / "api" / "service.py").write_text("VALUE = 'api'\n", encoding="utf-8")
    (root / "src" / "worker" / "job.py").write_text("VALUE = 'worker'\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--all"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "rooms"], check=True, capture_output=True)
    with mock.patch.dict(os.environ, {"AG2C_DATA_ROOT": str(base / "ag2c-data")}, clear=False):
        result = enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
    store = Path(result["store"])
    scratch = base / "scratch"
    write_project(scratch, gated=True)
    shutil.copy2(scratch / ".ag2c" / "policy.json", store / "policy.json")
    return root


def _store_policy(root: Path) -> Path:
    manifest = load_manifest(discover_manifest(root), project_root=root)
    return manifest.policy_path


def _mutate_card_jurisdiction(root: Path, card_id: str, **fields: str) -> None:
    """改夹具卡片的 jurisdiction 维度（推导规则测试的输入）。"""
    path = _store_policy(root)
    policy = json.loads(path.read_text(encoding="utf-8"))
    for card in policy["cards"]:
        if card.get("id") == card_id:
            card.setdefault("jurisdiction", {}).update(fields)
    path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")


def _start(root: Path, task_goal: str = "change", **kwargs):
    kwargs.setdefault("path_specs", ["app:src/api/service.py"])
    kwargs.setdefault("contract_specs", [])
    kwargs.setdefault("portrait", PORTRAIT)
    kwargs.setdefault("worktree_root", root.parent / "worktrees")
    return start_task(root, goal=task_goal, **kwargs)


def _task_record(root: Path, task_id: str) -> dict:
    manifest = load_manifest(discover_manifest(root), project_root=root)
    return json.loads((manifest.state_dir / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))


def _warning_history(root: Path) -> dict:
    manifest = load_manifest(discover_manifest(root), project_root=root)
    path = manifest.state_dir / "warning-history.json"
    if not path.is_file():
        return {"warnings": {}}
    return json.loads(path.read_text(encoding="utf-8"))


class CoordinateEnumTests(unittest.TestCase):
    """承诺①：封闭枚举校验——未知维度、非法值当场拒绝；合法全集接受。"""

    def test_full_legal_set_accepted(self) -> None:
        declaration = {
            "effect": "external",
            "contract": "machine",
            "meaning": "projection",
            "quality": "gold",
            "decider": "review",
            "grain": "conversation",
            "failure": "escalate",
        }
        self.assertEqual(declaration, validate_declaration(declaration))

    def test_unknown_dimension_refused(self) -> None:
        with self.assertRaises(AG2CError):
            validate_declaration({"effect": "write", "scope": "big"})

    def test_illegal_value_refused_with_legal_list(self) -> None:
        with self.assertRaises(AG2CError) as ctx:
            validate_declaration({"decider": "ai"})
        message = str(ctx.exception)
        self.assertIn("decider", message)
        self.assertIn("review", message)  # 拒绝输出列出合法取值

    def test_agf_enum_alignment(self) -> None:
        """枚举与 AGF 仓（agf/src/agf/models.py）逐字对齐的回归锚。"""
        from ag2c.coordinates import COORDINATE_ENUMS

        self.assertEqual(
            ("effect", "contract", "meaning", "quality", "decider", "grain", "failure"),
            COORDINATE_FIELDS,
        )
        self.assertEqual(
            {
                "effect": ("none", "read", "write", "external", "irreversible"),
                "contract": ("none", "partial", "machine"),
                "meaning": ("none", "summary", "projection"),
                "quality": ("none", "heuristic", "human", "gold"),
                "decider": ("none", "machine", "confirm", "review"),
                "grain": ("step", "run", "flow", "conversation"),
                "failure": ("fail_closed", "retry", "skip", "escalate"),
            },
            COORDINATE_ENUMS,
        )


class CoordinateDerivationTests(unittest.TestCase):
    """承诺②③：推导直通、多卡冲突取严、申报优先、三桶来源标注。"""

    def test_direct_mapping_and_named_to_summary(self) -> None:
        jurisdictions = [
            {"contract": "machine", "decider": "confirm", "meaning": "named", "grain": "module"},
        ]
        derived = derive_from_cards(jurisdictions)
        self.assertEqual("machine", derived["contract"])
        self.assertEqual("confirm", derived["decider"])
        self.assertEqual("summary", derived["meaning"])
        self.assertNotIn("grain", derived)  # 结构粒度≠时间粒度，不映射

    def test_multi_card_conflict_takes_stricter(self) -> None:
        jurisdictions = [
            {"contract": "partial", "decider": "none", "meaning": "none"},
            {"contract": "machine", "decider": "confirm", "meaning": "named"},
        ]
        derived = derive_from_cards(jurisdictions)
        self.assertEqual("machine", derived["contract"])  # machine > partial
        self.assertEqual("confirm", derived["decider"])  # confirm > none
        self.assertEqual("summary", derived["meaning"])  # summary > none

    def test_declaration_wins_over_derivation(self) -> None:
        resolved = resolve_coordinates(
            {"contract": "partial"},
            [{"contract": "machine", "decider": "confirm", "meaning": "named"}],
        )
        self.assertEqual("partial", resolved["effective"]["contract"])  # 申报优先
        self.assertEqual({"contract": "partial"}, resolved["declared"])
        self.assertEqual("confirm", resolved["derived"]["decider"])
        self.assertEqual("summary", resolved["derived"]["meaning"])
        # 卡片覆盖不到的维度落保守默认桶
        self.assertEqual("write", resolved["defaults"]["effect"])
        self.assertEqual("fail_closed", resolved["defaults"]["failure"])
        self.assertEqual("run", resolved["defaults"]["grain"])
        self.assertEqual("none", resolved["defaults"]["quality"])
        # 三桶互不相交，effective 是合并
        for dim in COORDINATE_FIELDS:
            buckets = [dim in resolved[key] for key in ("declared", "derived", "defaults")]
            self.assertEqual(1, sum(buckets), dim)
            self.assertIn(dim, resolved["effective"])

    def test_no_cards_all_defaults(self) -> None:
        resolved = resolve_coordinates(None, [])
        self.assertEqual({}, resolved["declared"])
        self.assertEqual({}, resolved["derived"])
        self.assertEqual(dict(CONSERVATIVE_DEFAULTS), resolved["effective"])


class ConstraintWarningTests(unittest.TestCase):
    """承诺④：quality=human 而 decider 不到人 → 警告（不拦）。"""

    def test_human_quality_without_human_decider_warns(self) -> None:
        warnings = constraint_warnings("t-x", {"quality": "human", "decider": "machine"})
        self.assertEqual(1, len(warnings))
        self.assertEqual(CONSTRAINT_WARNING_KIND, warnings[0]["kind"])
        self.assertEqual("t-x:quality-human-decider", warnings[0]["key"])

    def test_human_quality_with_confirm_decider_silent(self) -> None:
        self.assertEqual([], constraint_warnings("t-x", {"quality": "human", "decider": "confirm"}))
        self.assertEqual([], constraint_warnings("t-x", {"quality": "human", "decider": "review"}))
        self.assertEqual([], constraint_warnings("t-x", {"quality": "heuristic", "decider": "none"}))


class StartIntegrationTests(unittest.TestCase):
    """承诺③④的 start 级集成：记录三桶落账、约束警告进 warning-history、start 不拦。"""

    def test_start_records_three_buckets_and_ledger_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            _mutate_card_jurisdiction(root, "knowledge.api", contract="machine", decider="confirm")
            started = _start(root, coordinates={"quality": "heuristic"})
            record = _task_record(root, started["id"])
            coordinates = record["coordinates"]
            self.assertEqual({"quality": "heuristic"}, coordinates["declared"])
            self.assertEqual("machine", coordinates["derived"]["contract"])
            self.assertEqual("confirm", coordinates["derived"]["decider"])
            self.assertEqual("summary", coordinates["derived"]["meaning"])  # 夹具卡 meaning=named
            self.assertEqual("write", coordinates["defaults"]["effect"])
            self.assertEqual("heuristic", coordinates["effective"]["quality"])
            self.assertEqual("machine", coordinates["effective"]["contract"])
            # 账本事件携带坐标——后续对账的数据源
            manifest = load_manifest(discover_manifest(root), project_root=root)
            from ag2c.ledger import read_events

            events = [
                event
                for event in read_events(manifest.ledger_path)
                if event.get("event_type") == "task-started" and event.get("payload", {}).get("task_id") == started["id"]
            ]
            self.assertEqual(1, len(events))
            self.assertEqual(coordinates, events[0]["payload"]["coordinates"])

    def test_constraint_warning_recorded_not_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            # 夹具卡 decider=none；申报 quality=human → 约束警告
            started = _start(root, coordinates={"quality": "human"})
            record = _task_record(root, started["id"])
            self.assertEqual("none", record["coordinates"]["effective"]["decider"])
            history = _warning_history(root)
            hits = [
                entry
                for entry in history.get("warnings", {}).values()
                if entry.get("kind") == CONSTRAINT_WARNING_KIND and entry.get("key") == f"{started['id']}:quality-human-decider"
            ]
            self.assertEqual(1, len(hits))
            self.assertEqual(1, hits[0]["count"])  # 计数留痕，但 start 已正常返回（不拦）

    def test_no_warning_when_decider_declared_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            started = _start(root, coordinates={"quality": "human", "decider": "confirm"})
            history = _warning_history(root)
            hits = [
                entry
                for entry in history.get("warnings", {}).values()
                if entry.get("kind") == CONSTRAINT_WARNING_KIND
            ]
            self.assertEqual([], hits)
            record = _task_record(root, started["id"])
            self.assertEqual("confirm", record["coordinates"]["effective"]["decider"])

    def test_invalid_coordinate_refused_before_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            with self.assertRaises(AG2CError):
                _start(root, coordinates={"decider": "ai"})
            # 任务不创建、不留 worktree
            self.assertEqual([], list((root.parent / "worktrees").glob("*")))


class StartEvidenceCompatTests(unittest.TestCase):
    """承诺⑤：start 证据校验——新任务绑坐标，旧任务（事件无 coordinates 键）不受影响。"""

    def _bind_start_event(self, root: Path, task: dict, *, with_coordinates: bool) -> None:
        manifest = load_manifest(discover_manifest(root), project_root=root)
        payload = {
            "task_id": task["id"],
            "goal": task.get("goal"),
            "source_head": task.get("source", {}).get("head"),
            "source_branch": task.get("source", {}).get("branch"),
            "worktree": task.get("worktree", {}).get("path"),
            "worktree_branch": task.get("worktree", {}).get("branch"),
            "slice_digest": task.get("route", {}).get("slice_digest"),
            "route_state": task.get("route", {}).get("state"),
        }
        if with_coordinates:
            payload["coordinates"] = task.get("coordinates")
        event = append_event(manifest.ledger_path, "task-started", payload)
        task["start_ledger_event_digest"] = event["event_digest"]

    def test_new_task_coordinates_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            started = _start(root, coordinates={"quality": "gold"})
            record = _task_record(root, started["id"])
            # 真实 start 事件已带 coordinates → 证据有效
            manifest = load_manifest(discover_manifest(root), project_root=root)
            self.assertTrue(_start_evidence_valid(manifest, record))
            # 篡改记录里的坐标 → 证据失效
            record["coordinates"]["effective"]["quality"] = "none"
            self.assertFalse(_start_evidence_valid(manifest, record))

    def test_legacy_task_without_coordinates_stays_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            started = _start(root)
            record = _task_record(root, started["id"])
            # 模拟旧任务：事件不带 coordinates 键（结果门之前的任务也没有 portrait 键，
            # 同款条件绑定）。重绑一条无坐标键的 start 事件。
            record.pop("coordinates", None)
            record.pop("start_ledger_event_digest", None)
            self._bind_start_event(root, record, with_coordinates=False)
            manifest = load_manifest(discover_manifest(root), project_root=root)
            self.assertTrue(_start_evidence_valid(manifest, record))


class EntryPointTests(unittest.TestCase):
    """承诺①的双入口：CLI --coordinate 与 MCP coordinates 对象都真走一遍。"""

    def test_cli_start_with_coordinates(self) -> None:
        import io
        from contextlib import redirect_stdout

        from ag2c.cli_main import main

        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            previous = os.getcwd()
            output = io.StringIO()
            try:
                os.chdir(root)
                with redirect_stdout(output):
                    exit_code = main(
                        [
                            "task",
                            "start",
                            "--goal",
                            "change",
                            "--path",
                            "app:src/api/service.py",
                            "--portrait",
                            PORTRAIT,
                            "--worktree-root",
                            str(root.parent / "worktrees"),
                            "--coordinate",
                            "quality=human",
                            "--coordinate",
                            "decider=review",
                        ]
                    )
            finally:
                os.chdir(previous)
            self.assertEqual(0, exit_code)
            payload = json.loads(output.getvalue())
            coordinates = payload["coordinates"]
            self.assertEqual({"quality": "human", "decider": "review"}, coordinates["declared"])
            self.assertEqual("review", coordinates["effective"]["decider"])

    def test_cli_repeated_dimension_refused(self) -> None:
        import io
        from contextlib import redirect_stderr

        from ag2c.cli_main import main

        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            previous = os.getcwd()
            try:
                os.chdir(root)
                with redirect_stderr(io.StringIO()):
                    exit_code = main(
                        [
                            "task",
                            "start",
                            "--goal",
                            "change",
                            "--path",
                            "app:src/api/service.py",
                            "--portrait",
                            PORTRAIT,
                            "--worktree-root",
                            str(root.parent / "worktrees"),
                            "--coordinate",
                            "quality=human",
                            "--coordinate",
                            "quality=gold",
                        ]
                    )
            finally:
                os.chdir(previous)
            self.assertEqual(2, exit_code)  # AG2CError → 非零退出

    def test_mcp_start_with_coordinates_and_schema(self) -> None:
        from ag2c.mcp_server import HANDLERS, tool_defs

        schema = next(item for item in tool_defs() if item["name"] == "ag2c_task_start")
        self.assertIn("coordinates", schema["inputSchema"]["properties"])
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            result = HANDLERS["ag2c_task_start"](
                {
                    "cwd": str(root),
                    "goal": "change",
                    "portrait": PORTRAIT,
                    "paths": ["app:src/api/service.py"],
                    "coordinates": {"failure": "escalate"},
                }
            )
            record = _task_record(root, result["id"])
            self.assertEqual({"failure": "escalate"}, record["coordinates"]["declared"])
            self.assertEqual("escalate", record["coordinates"]["effective"]["failure"])

    def test_mcp_non_object_coordinates_refused(self) -> None:
        from ag2c.mcp_server import HANDLERS

        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            with self.assertRaises(AG2CError):
                HANDLERS["ag2c_task_start"](
                    {
                        "cwd": str(root),
                        "goal": "change",
                        "portrait": PORTRAIT,
                        "paths": ["app:src/api/service.py"],
                        "coordinates": "quality=human",
                    }
                )


# --- 对账三件套第二件：枚举对账机器锚 + 申报 vs 推导对账 ---

_SNAPSHOT_PATH = Path(__file__).parent / "agf_enums_snapshot.json"

#: AGF 七维维度名 → models.py 里的模块级集合符号。
_AGF_ENUM_SYMBOLS = {
    "effect": "EFFECTS",
    "contract": "CONTRACTS",
    "meaning": "MEANINGS",
    "quality": "QUALITIES",
    "decider": "DECIDERS",
    "grain": "GRAINS",
    "failure": "FAILURES",
}


def _load_snapshot() -> dict:
    return json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _agf_live_enums(models_path: Path) -> dict[str, list[str]]:
    """ast 解析 AGF models.py 提取七维枚举成员（指针而非引擎：读源码当数据，不 import agf）。"""
    import ast

    tree = ast.parse(models_path.read_text(encoding="utf-8"))
    found: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        for dim, symbol in _AGF_ENUM_SYMBOLS.items():
            if target.id != symbol:
                continue
            if not isinstance(node.value, (ast.Set, ast.Tuple, ast.List)):
                raise AssertionError(f"AGF {symbol} 不再是字面集合，快照口径失效")
            values = []
            for elt in node.value.elts:
                if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
                    raise AssertionError(f"AGF {symbol} 含非字符串字面量，快照口径失效")
                values.append(elt.value)
            found[dim] = sorted(values)
    return found


class EnumSnapshotTests(unittest.TestCase):
    """对账①：枚举对齐从注释锚升级为机器锚——coordinates.py == vendored 快照 == AGF 实况。 成员口径对账：AGF 用无序 set，AG2C 用有序 tuple（顺序承载严格度 rank， 是 AG2C 自己的语义），所以对账只比成员集合，不比顺序。"""

    def test_coordinates_match_snapshot(self) -> None:
        snapshot = _load_snapshot()
        self.assertEqual("ag2c.agf-enums-snapshot/v1", snapshot["schema"])
        self.assertEqual(sorted(COORDINATE_FIELDS), sorted(snapshot["enums"]))
        for dim in COORDINATE_FIELDS:
            self.assertEqual(
                sorted(snapshot["enums"][dim]),
                sorted(COORDINATE_ENUMS[dim]),
                f"{dim} 与 vendored 快照漂移：AG2C 改了枚举却没同步快照（或反之）",
            )

    def test_snapshot_matches_live_agf_repo(self) -> None:
        """AGF 仓在本机时校验快照==实况；仓不在跳过（CI 不能依赖邻居仓）。"""
        snapshot = _load_snapshot()
        source = snapshot["source"]
        repo = Path(os.environ.get(source["env_override"]) or source["repo_hint"])
        models = repo / source["file"]
        if not models.is_file():
            self.skipTest(f"AGF 仓不在本机（{models}），跳过实况对账")
        live = _agf_live_enums(models)
        self.assertEqual(sorted(COORDINATE_FIELDS), sorted(live))
        for dim in COORDINATE_FIELDS:
            self.assertEqual(
                sorted(snapshot["enums"][dim]),
                live[dim],
                f"{dim} 快照落后于 AGF 仓实况：AGF 修宪后需人工吸收（vendored 快照是有意识的同步点）",
            )


class ReconciliationWarningTests(unittest.TestCase):
    """对账②函数级：申报比推导宽松（rank 更低）才警告；更严/一致/无从对账都静默。"""

    def test_looser_declaration_warns(self) -> None:
        warnings = reconciliation_warnings("t-x", {"meaning": "none"}, {"meaning": "summary"})
        self.assertEqual(1, len(warnings))
        self.assertEqual(RECONCILIATION_WARNING_KIND, warnings[0]["kind"])
        self.assertEqual("meaning-declared-looser", warnings[0]["key"])
        self.assertIn("meaning=none", warnings[0]["detail"])
        self.assertIn("summary", warnings[0]["detail"])

    def test_stricter_or_equal_declaration_silent(self) -> None:
        self.assertEqual([], reconciliation_warnings("t-x", {"meaning": "projection"}, {"meaning": "summary"}))
        self.assertEqual([], reconciliation_warnings("t-x", {"contract": "machine"}, {"contract": "machine"}))

    def test_underivable_dimensions_not_reconciled(self) -> None:
        # effect/quality/failure/grain 卡片推导不出；declared 有而 derived 无 → 无从对账
        self.assertEqual([], reconciliation_warnings("t-x", {"quality": "none"}, {"contract": "machine"}))
        self.assertEqual([], reconciliation_warnings("t-x", {}, {"contract": "machine"}))
        self.assertEqual([], reconciliation_warnings("t-x", {"contract": "none"}, {}))

    def test_multiple_looser_dimensions_each_warn(self) -> None:
        warnings = reconciliation_warnings(
            "t-x",
            {"contract": "none", "decider": "machine"},
            {"contract": "partial", "decider": "confirm"},
        )
        self.assertEqual({"contract-declared-looser", "decider-declared-looser"}, {w["key"] for w in warnings})


class ReconciliationWiringTests(unittest.TestCase):
    """对账②的 verify 接线：真实 verify_task 驱动——警告进 verify 记录 + warning-history，且不拦。"""

    @staticmethod
    def _touch_and_verify(root: Path, started: dict) -> dict:
        from support import record_census

        from ag2c.tasks import verify_task

        worktree = Path(started["worktree"]["path"])
        service = worktree / "src" / "api" / "service.py"
        service.write_text(service.read_text(encoding="utf-8") + "# touched\n", encoding="utf-8")
        record_census(worktree)
        return verify_task(worktree)

    def test_verify_warns_on_looser_declaration_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            # 夹具卡 meaning=named → 推导 summary；申报 none 比推导宽松
            started = _start(root, coordinates={"meaning": "none"})
            report = self._touch_and_verify(root, started)
            self.assertTrue(report["passed"])  # 警告级：不拦
            reconciliation = report["verification"]["coordinate_reconciliation"]
            self.assertEqual({"meaning": "none"}, reconciliation["declared"])
            self.assertEqual("summary", reconciliation["derived"]["meaning"])
            keys = [w["key"] for w in reconciliation["warnings"]]
            self.assertEqual(["meaning-declared-looser"], keys)
            history = _warning_history(root)
            hits = [
                entry
                for entry in history.get("warnings", {}).values()
                if entry.get("kind") == RECONCILIATION_WARNING_KIND
            ]
            self.assertEqual(1, len(hits))
            self.assertEqual("meaning-declared-looser", hits[0]["key"])
            self.assertEqual(1, hits[0]["count"])

    def test_verify_silent_when_declaration_not_looser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            # projection 比推导的 summary 严——保守方向，不警告
            started = _start(root, coordinates={"meaning": "projection"})
            report = self._touch_and_verify(root, started)
            self.assertTrue(report["passed"])
            reconciliation = report["verification"]["coordinate_reconciliation"]
            self.assertEqual([], reconciliation["warnings"])
            history = _warning_history(root)
            hits = [
                entry
                for entry in history.get("warnings", {}).values()
                if entry.get("kind") == RECONCILIATION_WARNING_KIND
            ]
            self.assertEqual([], hits)

    def test_verify_reconciliation_absent_without_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            started = _start(root)  # 无申报 → 无从对账
            report = self._touch_and_verify(root, started)
            self.assertTrue(report["passed"])
            self.assertEqual({"warnings": []}, report["verification"]["coordinate_reconciliation"])


class DowngradeRatchetTests(unittest.TestCase):
    """降档棘轮：同维宽松申报跨任务计数，第三次硬化；约束警告永不硬化。"""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        (self._tmp / "state").mkdir(parents=True)
        self.manifest = Manifest(
            path=self._tmp / "manifest.json",
            project_id="test-proj",
            project_root=self._tmp,
            targets=[],
            ledger_path=self._tmp / "ledger.jsonl",
            policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )

    def test_reconciliation_escalates_on_third_task(self) -> None:
        warning = {
            "kind": RECONCILIATION_WARNING_KIND,
            "key": "meaning-declared-looser",
            "detail": "申报 meaning=none 比推导 summary 宽松",
        }
        self.assertEqual([], _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-1"))
        self.assertEqual([], _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-2"))
        escalated = _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-3")
        self.assertEqual(1, len(escalated))
        self.assertEqual("meaning-declared-looser", escalated[0]["key"])

    def test_constraint_never_escalates(self) -> None:
        warning = {
            "kind": CONSTRAINT_WARNING_KIND,
            "key": "t:quality-human-decider",
            "detail": "quality=human 但 decider=none",
        }
        for i in range(WARNING_ESCALATION_THRESHOLD + 2):
            self.assertEqual(
                [],
                _record_warnings_and_find_escalated(self.manifest, [warning], count_key=f"task-{i}"),
            )
