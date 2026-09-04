from pathlib import Path

from app.main import app


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_UI_ROOTS = (
    ROOT / "frontend" / "src" / "components",
    ROOT / "frontend" / "src" / "pages",
)


def test_ui_does_not_depend_on_api_client_or_literal_api_routes() -> None:
    violations: list[str] = []
    for root in FRONTEND_UI_ROOTS:
        for path in sorted(root.rglob("*.tsx")):
            if path.name.endswith(".test.tsx"):
                continue
            text = path.read_text(encoding="utf-8")
            if "apiFetch" in text:
                violations.append(str(path.relative_to(ROOT)))
            if "'/api/" in text or '"/api/' in text:
                violations.append(f"{path.relative_to(ROOT)} (literal /api route)")

    assert not violations, (
        "UI must call feature services instead of knowing HTTP transport/routes:\n"
        + "\n".join(violations)
    )


def test_material_chapter_contract_is_exposed_in_openapi() -> None:
    schema = app.openapi()
    path = schema["paths"]["/api/materials/{material_id}/chapters"]["get"]
    success = path["responses"]["200"]["content"]["application/json"]["schema"]

    assert success["type"] == "array"
    assert success["items"]["$ref"].endswith("/MaterialChapterResponse")
