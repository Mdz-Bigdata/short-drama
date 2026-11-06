# -*- coding: utf-8 -*-
"""The platform schema at startup, and the rule it exists for: financial records outlive the account."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete, inspect, text
from sqlalchemy.exc import IntegrityError

from app.platform.migrate import BASELINE_REVISION
from app.platform.models import PlatformUser
from app.platform.store import PlatformStore

HEAD = "0004_refund_approvals"
FINANCIAL = ("payment_orders", "billing_ledger", "user_memberships")

# The financial tables as ``create_all`` made them before this rule.
OLD_TABLES = """
CREATE TABLE platform_users (
    id VARCHAR(36) NOT NULL PRIMARY KEY, username VARCHAR(80) NOT NULL UNIQUE, email VARCHAR(320) UNIQUE,
    phone VARCHAR(32) UNIQUE, password_hash TEXT NOT NULL, role VARCHAR(24) NOT NULL, status VARCHAR(24) NOT NULL,
    display_name VARCHAR(120), must_change_password BOOLEAN NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
);
CREATE TABLE membership_plans (
    id VARCHAR(40) NOT NULL PRIMARY KEY, name VARCHAR(100) NOT NULL, description TEXT NOT NULL, price NUMERIC(18, 2) NOT NULL,
    currency VARCHAR(12) NOT NULL, points INTEGER NOT NULL, duration_days INTEGER NOT NULL, active BOOLEAN NOT NULL
);
CREATE TABLE user_memberships (
    user_id VARCHAR(36) NOT NULL PRIMARY KEY, plan_id VARCHAR(40) NOT NULL, status VARCHAR(24) NOT NULL,
    started_at DATETIME NOT NULL, expires_at DATETIME NOT NULL,
    FOREIGN KEY(user_id) REFERENCES platform_users (id) ON DELETE CASCADE, FOREIGN KEY(plan_id) REFERENCES membership_plans (id)
);
CREATE TABLE payment_orders (
    id VARCHAR(36) NOT NULL PRIMARY KEY, user_id VARCHAR(36) NOT NULL, plan_id VARCHAR(40) NOT NULL, provider VARCHAR(24) NOT NULL,
    amount NUMERIC(18, 2) NOT NULL, currency VARCHAR(12) NOT NULL, status VARCHAR(24) NOT NULL, idempotency_key VARCHAR(120) NOT NULL,
    provider_event_id VARCHAR(160) UNIQUE, created_at DATETIME NOT NULL, paid_at DATETIME,
    CONSTRAINT uq_order_user_key UNIQUE (user_id, idempotency_key),
    FOREIGN KEY(user_id) REFERENCES platform_users (id) ON DELETE CASCADE, FOREIGN KEY(plan_id) REFERENCES membership_plans (id)
);
CREATE INDEX ix_payment_orders_user_id ON payment_orders (user_id);
CREATE TABLE billing_ledger (
    id VARCHAR(36) NOT NULL PRIMARY KEY, user_id VARCHAR(36) NOT NULL, order_id VARCHAR(36), asset VARCHAR(24) NOT NULL,
    direction VARCHAR(12) NOT NULL, amount NUMERIC(18, 4) NOT NULL, currency VARCHAR(12) NOT NULL, category VARCHAR(80) NOT NULL,
    idempotency_key VARCHAR(180) NOT NULL UNIQUE, metadata_json JSON NOT NULL, created_at DATETIME NOT NULL,
    FOREIGN KEY(user_id) REFERENCES platform_users (id) ON DELETE CASCADE, FOREIGN KEY(order_id) REFERENCES payment_orders (id)
);
INSERT INTO platform_users VALUES ('u1', 'buyer', 'b@x.test', NULL, 'h', 'user', 'active', NULL, 0, '2026-01-01', '2026-01-01');
INSERT INTO membership_plans VALUES ('starter', 'S', '', 29.00, 'CNY', 500, 30, 1);
INSERT INTO user_memberships VALUES ('u1', 'starter', 'active', '2026-01-01 00:00:00', '2026-02-01 00:00:00');
INSERT INTO payment_orders VALUES ('o1', 'u1', 'starter', 'sandbox', 29.00, 'CNY', 'paid', 'key-00001', 'sandbox:o1', '2026-01-01', '2026-01-01');
INSERT INTO billing_ledger VALUES ('l1', 'u1', 'o1', 'points', 'credit', 500, 'PTS', 'membership_purchase', 'order:o1:points', '{}', '2026-01-01');
"""


class SchemaUpgradeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "platform.sqlite3"
        self.store = PlatformStore(f"sqlite+aiosqlite:///{self.path}")
        self.addAsyncCleanup(self.store.close)

    async def _version(self):
        async with self.store.engine.connect() as connection:
            return await connection.scalar(text("SELECT version_num FROM alembic_version"))

    async def _on_delete(self):
        def read(connection):
            inspector = inspect(connection)
            return {
                table: next(
                    key["options"].get("ondelete") for key in inspector.get_foreign_keys(table)
                    if key["referred_table"] == "platform_users"
                ) for table in FINANCIAL
            }
        async with self.store.engine.connect() as connection:
            return await connection.run_sync(read)

    async def _delete_user(self, user_id):
        async with self.store.sessions() as session:
            await session.execute(delete(PlatformUser).where(PlatformUser.id == user_id))
            await session.commit()

    def _old_database(self, *, version=None):
        connection = sqlite3.connect(self.path)
        connection.executescript(OLD_TABLES)
        if version:
            connection.executescript(
                f"CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY); "
                f"INSERT INTO alembic_version VALUES ('{version}');"
            )
        connection.commit()
        connection.close()

    async def test_a_new_database_starts_at_the_latest_revision_with_the_rule_in_place(self):
        await self.store.create_schema()
        self.assertEqual(await self._version(), HEAD)
        self.assertEqual(set((await self._on_delete()).values()), {"RESTRICT"})

    async def test_a_database_from_before_migrations_keeps_its_data_and_gains_the_rule(self):
        self._old_database()
        await self.store.create_schema()
        self.assertEqual(await self._version(), HEAD)
        self.assertEqual(set((await self._on_delete()).values()), {"RESTRICT"})
        async with self.store.engine.connect() as connection:
            for table, count in (("payment_orders", 1), ("billing_ledger", 1), ("user_memberships", 1), ("platform_users", 1)):
                self.assertEqual(await connection.scalar(text(f"SELECT count(*) FROM {table}")), count, table)
            self.assertEqual(await connection.scalar(text("SELECT amount FROM billing_ledger")), 500)
        def indexes(connection):
            inspector = inspect(connection)
            return (
                {index["name"] for index in inspector.get_indexes("payment_orders")},
                {key["name"] for key in inspector.get_unique_constraints("payment_orders")},
            )
        async with self.store.engine.connect() as connection:
            names, uniques = await connection.run_sync(indexes)
        self.assertIn("ix_payment_orders_user_id", names)
        self.assertIn("uq_order_user_key", uniques)

    async def test_after_the_upgrade_a_buyer_cannot_be_deleted(self):
        self._old_database()
        await self.store.create_schema()
        with self.assertRaises(IntegrityError):
            await self._delete_user("u1")
        async with self.store.engine.connect() as connection:
            self.assertEqual(await connection.scalar(text("SELECT count(*) FROM billing_ledger")), 1)

    async def test_running_again_changes_nothing(self):
        self._old_database()
        await self.store.create_schema()
        await self.store.create_schema()
        self.assertEqual(await self._version(), HEAD)

    async def test_a_database_already_on_a_revision_only_runs_what_is_new(self):
        self._old_database(version=BASELINE_REVISION)
        await self.store.create_schema()
        self.assertEqual(await self._version(), HEAD)
        self.assertEqual(set((await self._on_delete()).values()), {"RESTRICT"})

    async def test_tables_from_before_refund_approvals_gain_their_columns_and_keep_their_rows(self):
        await self.store.create_schema()
        user, _ = await self.store.create_user(email="lots@example.com", phone=None, password="lots-password")
        async with self.store.engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO point_balances (user_id, available, held, frozen) VALUES (:user, 7, 0, 0)"), {"user": user.id},
            )
            await connection.execute(text("ALTER TABLE point_balances DROP COLUMN frozen"))
            await connection.execute(text("ALTER TABLE point_lots DROP COLUMN frozen"))
            await connection.execute(text("DROP TABLE payment_refunds"))
            await connection.execute(text(
                "CREATE TABLE payment_refunds (id VARCHAR(36) PRIMARY KEY, order_id VARCHAR(36), attempt_id VARCHAR(36), user_id VARCHAR(36), "
                "provider VARCHAR(24), out_trade_no VARCHAR(32), out_refund_no VARCHAR(64), channel_refund_no VARCHAR(64), refund_minor INTEGER, "
                "total_minor INTEGER, reason VARCHAR(40), status VARCHAR(24), detail VARCHAR(200), last_tried_at DATETIME, created_at DATETIME, finished_at DATETIME)"
            ))
            await connection.execute(text("UPDATE alembic_version SET version_num = '0003_user_roles'"))
        await self.store.create_schema()
        self.assertEqual(await self._version(), HEAD)
        async with self.store.engine.connect() as connection:
            row = (await connection.execute(text("SELECT available, frozen FROM point_balances"))).one()
            self.assertEqual((float(row[0]), float(row[1])), (7.0, 0.0))
            await connection.execute(text("SELECT frozen FROM point_lots"))
            await connection.execute(text("SELECT points_clawback, requested_by, approved_by, decided_at FROM payment_refunds"))

    async def test_foreign_keys_are_on_again_after_the_upgrade(self):
        self._old_database()
        await self.store.create_schema()
        async with self.store.engine.connect() as connection:
            self.assertEqual(await connection.scalar(text("PRAGMA foreign_keys")), 1)

    async def test_a_user_with_no_financial_records_can_still_be_removed(self):
        await self.store.create_schema()
        user, _ = await self.store.create_user(email="nobody@example.com", phone=None, password="nobody-password")
        await self._delete_user(user.id)
        self.assertIsNone(await self.store.get_user(user.id))


if __name__ == "__main__":
    unittest.main()
