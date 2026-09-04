import unittest
import warnings

from pydantic import BaseModel

from app.utils.pydantic_compat import provided_model_fields


class _PatchPayload(BaseModel):
    title: str | None = None
    parent_id: int | None = None


class PydanticCompatibilityTests(unittest.TestCase):
    def test_provided_fields_uses_the_v2_api_without_deprecation_warnings(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            payload = _PatchPayload(parent_id=None)
            fields = provided_model_fields(payload)

        self.assertEqual(fields, {"parent_id"})


if __name__ == "__main__":
    unittest.main()
