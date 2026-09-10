import unittest

import dr_postgres_verify


class DisasterRecoveryPostgresVerifyTests(unittest.TestCase):
    def test_identifier_validation_accepts_platform_contract(self):
        self.assertEqual(
            dr_postgres_verify.validate_identifier("litellm", "database"),
            "litellm",
        )
        self.assertEqual(
            dr_postgres_verify.validate_identifier("dr_restore_deadbeef", "database"),
            "dr_restore_deadbeef",
        )

    def test_identifier_validation_rejects_sql_metacharacters(self):
        for value in ("bad-name", "bad name", "x;DROP", "x' OR 1=1", "1bad", ""):
            with self.assertRaises(dr_postgres_verify.PostgresVerifyError):
                dr_postgres_verify.validate_identifier(value, "database")

    def test_admin_command_reads_secret_inside_container(self):
        command = dr_postgres_verify.docker_admin_prefix()
        rendered = " ".join(command)
        self.assertIn("/run/secrets/postgres_admin_password", rendered)
        self.assertIn("PGPASSWORD", rendered)
        self.assertNotIn("LITELLM_DB_PASSWORD", rendered)
        self.assertNotIn("postgres_admin_password=", rendered)

    def test_admin_user_is_postgres(self):
        self.assertEqual(dr_postgres_verify.ADMIN_USER, "postgres")
        self.assertEqual(dr_postgres_verify.SERVICE, "litellm-postgres")

    def test_quote_identifier_is_bounded_by_validator(self):
        self.assertEqual(dr_postgres_verify.quote_identifier("litellm"), '"litellm"')
        with self.assertRaises(dr_postgres_verify.PostgresVerifyError):
            dr_postgres_verify.quote_identifier('litellm";DROP DATABASE postgres;--')


if __name__ == "__main__":
    unittest.main()
