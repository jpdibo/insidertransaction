from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

from insider_tracker.backup import create_backup, restore_backup
from insider_tracker.audit import create_audit_sample
from insider_tracker.config import config_hash, load_config
from insider_tracker.db import connect, migrate
from insider_tracker.locking import LockBusy, ProcessLock
from insider_tracker.numbers import canonical_decimal, multiply, numeric_sort, parse_localized_decimal
from insider_tracker.pipeline import reconcile_cross_source_duplicates, recover_abandoned_runs, run_daily, seed_registry
from insider_tracker.web import application
from parsers.newsweb_json import parse as parse_newsweb

ROOT = Path(__file__).resolve().parents[1]


class SystemTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="insider-test-"))
        self.database = self.temp / "data" / "insiders.sqlite3"
        self.raw = self.temp / "data" / "raw"
        self.reports = self.temp / "data" / "reports"
        base = load_config(ROOT / "config" / "sources.yaml")
        base["sources"] = [source for source in base["sources"] if source["source_id"] == "offline_fixture_corpus"]
        base["sources"][0]["fixture_path"] = str(ROOT / "tests" / "fixtures" / "synthetic")
        self.config_path = self.temp / "sources.yaml"
        self.config_path.write_text(json.dumps(base), encoding="utf-8")
        self.config = load_config(self.config_path)
        self.connection = connect(self.database)
        migrate(self.connection, ROOT / "migrations")
        seed_registry(self.connection, self.config, config_hash(self.config_path))

    def tearDown(self):
        self.connection.close()
        shutil.rmtree(self.temp, ignore_errors=True)

    def ingest(self):
        return run_daily(self.connection, self.config, self.config_path, self.raw, self.reports, "2026-09-07T23:59:59Z")

    def test_audit_sample_is_bounded_and_deterministic(self):
        self.ingest()
        first = self.reports / "audit-first.csv"
        second = self.reports / "audit-second.csv"
        self.assertEqual(create_audit_sample(self.connection, "offline_fixture_corpus", 3, first), 3)
        self.assertEqual(create_audit_sample(self.connection, "offline_fixture_corpus", 3, second), 3)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertIn("decision,notes", first.read_text(encoding="utf-8-sig").splitlines()[0])

    def test_exact_decimals_and_locales(self):
        values = ["2", "10", "0.123456789123456789"]
        self.assertEqual(numeric_sort(values), ["0.123456789123456789", "2", "10"])
        self.assertEqual(canonical_decimal("0.123456789123456789"), "0.123456789123456789")
        self.assertEqual(parse_localized_decimal("1.234,56", "decimal_comma"), "1234.56")
        self.assertEqual(parse_localized_decimal("1 234,56", "decimal_comma"), "1234.56")
        self.assertEqual(parse_localized_decimal("1'234.56", "decimal_point"), "1234.56")
        self.assertEqual(multiply("10000", "245.50", "0.01"), "24550")

    def test_real_newsweb_fixture_preserves_unknown_currency(self):
        payload = parse_newsweb((ROOT / "tests" / "fixtures" / "real" / "newsweb" / "message-681721.json").read_bytes())
        filing = payload["filings"][0]
        group = filing["transaction_groups"][0]
        row = group["rows"][0]
        self.assertEqual(filing["transacting_party"]["name_raw"], "Janne Perlesentbakken")
        self.assertEqual(group["action"], "disposal")
        self.assertEqual(group["trade_date"], "2026-09-04")
        self.assertEqual(row["quantity"], "37556")
        self.assertIsNone(row["price_currency_normalized"])

    def test_unknown_currency_does_not_create_consideration(self):
        news_source = next(source for source in load_config(ROOT / "config" / "sources.yaml")["sources"] if source["source_id"] == "no_newsweb")
        news_source["adapter"] = "fixture_json"
        news_source["fixture_path"] = str(ROOT / "tests" / "fixtures" / "real" / "newsweb")
        self.config["sources"] = [news_source]
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        seed_registry(self.connection, self.config, config_hash(self.config_path))
        run_daily(self.connection, self.config, self.config_path, self.raw, self.reports, "2026-09-07T23:59:59Z")
        row = self.connection.execute("SELECT consideration_derived_decimal,consideration_currency FROM reported_transaction_rows").fetchone()
        self.assertEqual(tuple(row), (None, None))

    def test_replay_is_idempotent_and_aggregate_not_doubled(self):
        first = self.ingest()
        counts1 = tuple(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("economic_events", "event_versions", "outbox_events"))
        hashes1 = [row[0] for row in self.connection.execute("SELECT accepted_content_hash FROM event_versions ORDER BY economic_event_id")]
        second = self.ingest()
        counts2 = tuple(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("economic_events", "event_versions", "outbox_events"))
        hashes2 = [row[0] for row in self.connection.execute("SELECT accepted_content_hash FROM event_versions ORDER BY economic_event_id")]
        self.assertEqual(first.status, "success")
        self.assertEqual(second.status, "success")
        self.assertEqual(counts1, counts2)
        self.assertEqual(hashes1, hashes2)
        rows = self.connection.execute("SELECT representation,quantity_decimal,selected_for_analytics FROM reported_transaction_rows WHERE transaction_group_id=(SELECT id FROM transaction_groups WHERE group_locator='fills') ORDER BY occurrence_ordinal").fetchall()
        self.assertEqual([(row[0], row[1], row[2]) for row in rows], [("individual", "1000", 1), ("individual", "2000", 1), ("aggregate", "3000", 0)])
        selected_total = sum((__import__("decimal").Decimal(row[1]) for row in rows if row[2]), __import__("decimal").Decimal(0))
        self.assertEqual(selected_total, __import__("decimal").Decimal("3000"))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM filing_versions WHERE issuer_name_raw IS NULL").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM transaction_groups WHERE instrument_name_raw IS NULL").fetchone()[0], 0)

    def test_backfill_uses_independent_bounded_checkpoint(self):
        self.config["sources"][0]["backfill_start_date"] = "2026-08-01"
        self.config["sources"][0]["backfill_window_days"] = 3
        self.config["sources"][0]["backfill_enabled"] = True
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        config = load_config(self.config_path)
        run_daily(self.connection, config, self.config_path, self.raw, self.reports, "2026-09-07T23:59:59Z", mode="backfill")
        checkpoint = self.connection.execute("SELECT covered_through FROM source_checkpoints WHERE source_id='offline_fixture_corpus' AND mode='backfill'").fetchone()[0]
        self.assertEqual(checkpoint, "2026-08-03")
        self.assertIsNone(self.connection.execute("SELECT covered_through FROM source_checkpoints WHERE source_id='offline_fixture_corpus' AND mode='daily'").fetchone())

    def test_gbx_and_anonymous_identity(self):
        self.ingest()
        gbx = self.connection.execute("SELECT consideration_derived_decimal,price_per_unit_decimal FROM reported_transaction_rows WHERE price_raw='245.50 GBX'").fetchone()
        self.assertEqual(tuple(gbx), ("24550", "2.455"))
        anonymous = self.connection.execute("SELECT id,canonical_name,party_type FROM parties WHERE party_type='anonymous_role'").fetchone()
        self.assertIsNone(anonymous["canonical_name"])
        self.assertTrue(anonymous["id"].startswith("anon_"))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM parties WHERE canonical_name='Board Member'").fetchone()[0], 0)

    def test_correction_creates_revision_not_new_event(self):
        self.ingest()
        before = self.connection.execute("SELECT COUNT(*) FROM economic_events").fetchone()[0]
        self.config["sources"][0]["fixture_path"] = str(ROOT / "tests" / "fixtures" / "corrections")
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        corrected = load_config(self.config_path)
        result = run_daily(self.connection, corrected, self.config_path, self.raw, self.reports, "2026-09-08T23:59:59Z")
        self.assertEqual(result.sources[0].amended, 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM economic_events").fetchone()[0], before)
        versions = self.connection.execute("SELECT version_number,superseded_at FROM event_versions WHERE economic_event_id=(SELECT economic_event_id FROM event_versions ev JOIN transaction_groups tg ON tg.id=ev.transaction_group_id WHERE tg.group_locator='section-4' ORDER BY version_number LIMIT 1) ORDER BY version_number").fetchall()
        self.assertEqual(len(versions), 2)
        self.assertIsNotNone(versions[0]["superseded_at"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM outbox_events WHERE kind='correction'").fetchone()[0], 1)

    def test_correction_before_original_remains_current(self):
        self.config["sources"][0]["fixture_path"] = str(ROOT / "tests" / "fixtures" / "corrections")
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        corrected = load_config(self.config_path)
        run_daily(self.connection, corrected, self.config_path, self.raw, self.reports, "2026-09-08T23:59:59Z")
        corrected["sources"][0]["fixture_path"] = str(ROOT / "tests" / "fixtures" / "synthetic")
        self.config_path.write_text(json.dumps(corrected), encoding="utf-8")
        run_daily(self.connection, load_config(self.config_path), self.config_path, self.raw, self.reports, "2026-09-09T23:59:59Z")
        current = self.connection.execute(
            "SELECT r.quantity_decimal FROM economic_events e JOIN event_versions ev ON ev.id=e.current_version_id "
            "JOIN event_evidence ee ON ee.event_version_id=ev.id JOIN reported_transaction_rows r ON r.id=ee.reported_row_id "
            "WHERE r.price_raw='245.50 GBX'"
        ).fetchone()
        self.assertEqual(current["quantity_decimal"], "12000")
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM event_versions ev JOIN event_evidence ee ON ee.event_version_id=ev.id "
            "JOIN reported_transaction_rows r ON r.id=ee.reported_row_id WHERE r.price_raw='245.50 GBX'"
        ).fetchone()[0], 2)

    def test_unknown_layout_is_retained_and_quarantined(self):
        self.config["sources"][0]["fixture_path"] = str(ROOT / "tests" / "fixtures" / "invalid")
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        result = run_daily(self.connection, load_config(self.config_path), self.config_path, self.raw, self.reports, "2026-09-07T23:59:59Z")
        self.assertEqual(result.status, "partial_failure")
        self.assertEqual(result.sources[0].state, "quarantined")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM raw_objects").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM economic_events").fetchone()[0], 0)

    def test_writer_lock_rejects_overlap(self):
        path = self.temp / "lock"
        with ProcessLock(path):
            with self.assertRaises(LockBusy):
                with ProcessLock(path):
                    pass

    def test_stale_writer_lock_is_reclaimed(self):
        path = self.temp / "stale-lock"
        path.write_text("pid=2147483647\n", encoding="ascii")
        with ProcessLock(path):
            self.assertTrue(path.exists())
        self.assertFalse(path.exists())

    def test_windows_vanished_lock_owner_system_error_is_reclaimed(self):
        path = self.temp / "vanished-lock"
        path.write_text("pid=2147483646\n", encoding="ascii")
        with patch("insider_tracker.locking.os.kill", side_effect=SystemError("process exited")):
            with ProcessLock(path):
                self.assertTrue(path.exists())
        self.assertFalse(path.exists())

    def test_lock_exit_does_not_remove_replacement_owner(self):
        path = self.temp / "replacement-lock"
        lock = ProcessLock(path)
        lock.__enter__()
        path.write_text("pid=1\ntoken=replacement\n", encoding="ascii")
        lock.__exit__(None, None, None)
        self.assertTrue(path.exists())

    def test_abandoned_runs_are_finalized(self):
        self.connection.execute(
            "INSERT INTO ingestion_runs(id,mode,started_at,cutoff_at,status,code_version,config_hash) "
            "VALUES('abandoned','daily','2026-09-01T00:00:00Z','2026-09-01T00:00:00Z','running','test','test')"
        )
        self.connection.execute(
            "INSERT INTO run_tasks(run_id,source_id,state) VALUES('abandoned','offline_fixture_corpus','running')"
        )
        self.connection.commit()
        self.assertEqual(recover_abandoned_runs(self.connection), 1)
        self.assertEqual(self.connection.execute("SELECT status FROM ingestion_runs WHERE id='abandoned'").fetchone()[0], "interrupted")
        self.assertEqual(self.connection.execute("SELECT state FROM run_tasks WHERE run_id='abandoned'").fetchone()[0], "interrupted")

    def test_nullable_identifier_identity_is_unique(self):
        self.connection.execute("INSERT INTO issuers(id,legal_name) VALUES('issuer-a','Issuer A')")
        self.connection.execute("INSERT INTO issuer_identifiers(issuer_id,scheme,value) VALUES('issuer-a','LEI','52990000000000000001')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("INSERT INTO issuer_identifiers(issuer_id,scheme,value) VALUES('issuer-a','LEI','52990000000000000001')")

    def test_cross_source_duplicates_are_linked_not_merged(self):
        duplicate = dict(self.config["sources"][0])
        duplicate["source_id"] = "second_fixture_corpus"
        duplicate["name"] = "Second fixture corpus"
        self.config["sources"].append(duplicate)
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        config = load_config(self.config_path)
        seed_registry(self.connection, config, config_hash(self.config_path))
        run_daily(self.connection, config, self.config_path, self.raw, self.reports, "2026-09-07T23:59:59Z")
        event_count = self.connection.execute("SELECT COUNT(*) FROM economic_events").fetchone()[0]
        candidates = reconcile_cross_source_duplicates(self.connection)
        self.assertEqual(candidates, 6)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM event_links").fetchone()[0], 6)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM economic_events").fetchone()[0], event_count)

    def test_reparse_retracts_group_absent_from_corrected_payload(self):
        fixture_dir = self.temp / "changing-fixture"
        fixture_dir.mkdir()
        payload = json.loads((ROOT / "tests" / "fixtures" / "synthetic" / "005_option_and_sale.json").read_text(encoding="utf-8"))
        fixture = fixture_dir / "005_option_and_sale.json"
        fixture.write_text(json.dumps(payload), encoding="utf-8")
        self.config["sources"][0]["fixture_path"] = str(fixture_dir)
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        run_daily(self.connection, load_config(self.config_path), self.config_path, self.raw, self.reports, "2026-09-07T23:59:59Z")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM economic_events WHERE current_version_id IS NOT NULL").fetchone()[0], 2)
        payload["filings"][0]["transaction_groups"] = payload["filings"][0]["transaction_groups"][:1]
        payload["filings"][0]["notification_status"] = "amended"
        fixture.write_text(json.dumps(payload), encoding="utf-8")
        run_daily(self.connection, load_config(self.config_path), self.config_path, self.raw, self.reports, "2026-09-08T23:59:59Z")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM economic_events WHERE current_version_id IS NOT NULL").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM economic_events WHERE retracted_at IS NOT NULL").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM outbox_events WHERE kind='retraction'").fetchone()[0], 1)

    def test_scheduler_trigger_is_utc_and_dst_unambiguous(self):
        root = ET.fromstring((ROOT / "scheduler" / "InsiderTrackerDaily.xml").read_text(encoding="utf-16"))
        namespace = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        boundary = root.findtext(".//task:StartBoundary", namespaces=namespace)
        self.assertTrue(boundary.endswith("Z"))
        self.assertEqual(root.findtext(".//task:MultipleInstancesPolicy", namespaces=namespace), "IgnoreNew")
        self.assertEqual(root.findtext(".//task:StartWhenAvailable", namespaces=namespace), "true")

    def test_backup_restore_and_resume(self):
        self.ingest()
        bundle = create_backup(self.database, self.raw, self.temp / "backups", "test")
        destination = self.temp / "restored"
        restore_backup(bundle, destination)
        restored = connect(destination / "insiders.sqlite3")
        try:
            self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(restored.execute("SELECT COUNT(*) FROM economic_events").fetchone()[0], 6)
            self.assertEqual(restored.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            restored.close()

    def test_web_feed_api_and_csv(self):
        self.ingest()
        app = application(self.database)
        for path, expected_type in (("/", "text/html"), ("/coverage", "text/html"), ("/api/transactions", "application/json"), ("/export.csv", "text/csv")):
            environ = {}; setup_testing_defaults(environ); environ["PATH_INFO"] = path
            response = {}
            def start(status, headers): response.update(status=status, headers=dict(headers))
            body = b"".join(app(environ, start))
            self.assertEqual(response["status"], "200 OK")
            self.assertIn(expected_type, response["headers"]["Content-Type"])
            self.assertTrue(body)
            if path == "/":
                self.assertIn(b"trade 04 Sep 2026", body)
                self.assertNotIn(b"trade 04 Sep 2026 00:00", body)


if __name__ == "__main__":
    unittest.main()
