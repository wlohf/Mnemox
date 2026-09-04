import ast
import unittest
from pathlib import Path

from app.utils.transaction_policy import TRANSACTION_OWNERS, TransactionOwnerKind


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCANNED_ROOTS = (BACKEND_ROOT / "app" / "services", BACKEND_ROOT / "app" / "agents")


class _CommitCollector(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.scope: list[str] = []
        self.locations: dict[str, list[int]] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "commit":
            owner = ".".join((self.module, *self.scope))
            self.locations.setdefault(owner, []).append(node.lineno)
        self.generic_visit(node)


def _service_commit_locations() -> dict[str, list[int]]:
    discovered: dict[str, list[int]] = {}
    for root in SCANNED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            module = path.relative_to(BACKEND_ROOT).with_suffix("").as_posix().replace("/", ".")
            collector = _CommitCollector(module)
            collector.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
            discovered.update(collector.locations)
    return discovered


class TransactionOwnershipArchitectureTests(unittest.TestCase):
    def test_every_service_commit_has_an_explicit_owner_and_rationale(self):
        discovered = _service_commit_locations()

        missing = sorted(set(discovered) - set(TRANSACTION_OWNERS))
        stale = sorted(set(TRANSACTION_OWNERS) - set(discovered))
        self.assertEqual(
            missing,
            [],
            "Unregistered service commit owners: "
            + ", ".join(f"{name}:{discovered[name]}" for name in missing),
        )
        self.assertEqual(stale, [], "Stale transaction owner entries: " + ", ".join(stale))

        for name, owner in TRANSACTION_OWNERS.items():
            self.assertIn(owner.kind, set(TransactionOwnerKind), name)
            self.assertGreaterEqual(len(owner.rationale.strip()), 40, name)

    def test_read_only_profile_and_agent_tools_are_not_transaction_owners(self):
        forbidden = {
            "app.services.profile_service.compute_and_save_profile",
            "app.services.profile_service.get_or_compute_profile",
            "app.services.learning_snapshot_service.build_learning_snapshot",
            "app.agents.manager.AgentManager.call_chat_tool",
        }
        self.assertTrue(forbidden.isdisjoint(TRANSACTION_OWNERS))
        self.assertTrue(forbidden.isdisjoint(_service_commit_locations()))


if __name__ == "__main__":
    unittest.main()
