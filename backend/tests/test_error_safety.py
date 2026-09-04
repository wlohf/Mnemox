import unittest
from datetime import datetime
from types import SimpleNamespace

from app.agents.manager import agent_manager
from app.models.agent import AgentExecutionLog, AgentJob
from app.utils.ai_errors import format_ai_provider_error
from app.utils.error_safety import (
    error_fingerprint,
    redact_sensitive_text,
    safe_error_diagnostic,
    safe_exception_diagnostic,
    safe_exception_summary,
)


class ErrorSafetyTests(unittest.TestCase):
    def test_common_secret_shapes_are_redacted_without_losing_context(self):
        raw = (
            "upstream rejected Authorization: Bearer bearer-secret-12345; "
            "url=https://alice:database-password@example.test/v1?api_key=query-secret&x=1; "
            "payload={'password': 'open sesame', 'token': 'token-secret'}; "
            "provider=sk-proj-abcdefghijklmnop"
        )

        result = redact_sensitive_text(raw, max_chars=1000)

        self.assertIn("upstream rejected", result)
        self.assertIn("example.test", result)
        self.assertIn("[REDACTED]", result)
        self.assertEqual(result, redact_sensitive_text(result, max_chars=1000))
        for secret in (
            "bearer-secret-12345",
            "database-password",
            "query-secret",
            "open sesame",
            "token-secret",
            "sk-proj-abcdefghijklmnop",
        ):
            self.assertNotIn(secret, result)

    def test_json_authorization_and_private_key_are_redacted(self):
        raw = (
            '{"Authorization": "Bearer json-secret", "message": "denied"}\n'
            "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----"
        )

        result = redact_sensitive_text(raw, max_chars=1000)

        self.assertIn('"message": "denied"', result)
        self.assertNotIn("json-secret", result)
        self.assertNotIn("private-material", result)

    def test_exception_summary_is_single_line_bounded_and_correlatable(self):
        error = RuntimeError("provider failed\napi_key=secret-value " + "x" * 1000)

        summary = safe_exception_summary(error, max_chars=120)

        self.assertTrue(summary.startswith("RuntimeError: provider failed"))
        self.assertLessEqual(len(summary), 120)
        self.assertNotIn("\n", summary)
        self.assertNotIn("secret-value", summary)
        self.assertEqual(error_fingerprint(error), error_fingerprint(error))

    def test_structured_diagnostic_uses_caller_code_and_sanitized_fingerprint(self):
        error = RuntimeError("provider timeout api_key=diagnostic-secret")

        diagnostic = safe_exception_diagnostic(
            error,
            code="Provider / Timeout",
            max_chars=120,
        )
        reconstructed = safe_error_diagnostic(
            diagnostic.summary,
            code=diagnostic.code,
            max_chars=120,
        )

        self.assertEqual(diagnostic.code, "provider_timeout")
        self.assertIn("[REDACTED]", diagnostic.summary)
        self.assertNotIn("diagnostic-secret", diagnostic.summary)
        self.assertRegex(diagnostic.fingerprint, r"^[0-9a-f]{16}$")
        self.assertEqual(diagnostic.fingerprint, reconstructed.fingerprint)
        self.assertEqual(diagnostic.as_dict()["error_code"], "provider_timeout")

    def test_unknown_ai_provider_errors_are_safe_at_the_ui_boundary(self):
        message = format_ai_provider_error(
            RuntimeError("relay failed at https://example.test/v1?access_token=ui-secret")
        )

        self.assertIn("relay failed", message)
        self.assertIn("[REDACTED]", message)
        self.assertNotIn("ui-secret", message)

    def test_provider_response_body_is_redacted_before_reaching_the_ui(self):
        error = SimpleNamespace(
            status_code=400,
            response=SimpleNamespace(
                json=lambda: {"error": {"message": "bad request api_key=response-secret"}},
            ),
        )

        message = format_ai_provider_error(error)  # type: ignore[arg-type]

        self.assertIn("bad request", message)
        self.assertIn("[REDACTED]", message)
        self.assertNotIn("response-secret", message)

    def test_historical_agent_diagnostics_are_redacted_again_on_read(self):
        now = datetime(2026, 9, 2, 1, 2, 3)
        job = AgentJob(
            id="historical-job",
            user_id=1,
            agent="chat",
            task="run",
            status="failed",
            payload={},
            summary="legacy failure token=historical-secret",
            result={},
            created_at=now,
            updated_at=now,
        )
        log = AgentExecutionLog(
            id="historical-log",
            user_id=1,
            job_id=job.id,
            agent="chat",
            status="failed",
            message="Authorization: Bearer old-log-secret",
            created_at=now,
        )

        job_payload = agent_manager._job_to_dict(job)
        log_payload = agent_manager._log_to_dict(log)

        self.assertNotIn("historical-secret", job_payload["summary"])
        self.assertNotIn("old-log-secret", log_payload["message"])
        self.assertIn("[REDACTED]", job_payload["summary"])
        self.assertIn("[REDACTED]", log_payload["message"])
        self.assertEqual(job_payload["error_code"], "agent.execution_failed")
        self.assertRegex(job_payload["error_fingerprint"], r"^[0-9a-f]{16}$")


if __name__ == "__main__":
    unittest.main()
