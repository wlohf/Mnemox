import unittest

from app.utils.operation_lock import stable_advisory_lock_key


class OperationLockTests(unittest.TestCase):
    def test_advisory_key_is_stable_namespaced_and_signed_bigint_safe(self):
        first = stable_advisory_lock_key("retrieval_projection_user_v1", 42)
        repeated = stable_advisory_lock_key("retrieval_projection_user_v1", 42)
        other_user = stable_advisory_lock_key("retrieval_projection_user_v1", 43)
        other_namespace = stable_advisory_lock_key("another_operation", 42)

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, other_user)
        self.assertNotEqual(first, other_namespace)
        self.assertGreaterEqual(first, -(2**63))
        self.assertLessEqual(first, 2**63 - 1)


if __name__ == "__main__":
    unittest.main()
