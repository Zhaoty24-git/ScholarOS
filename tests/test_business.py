"""Synthetic adapter responses exercise the real parsers and persistence code."""
import argparse
from datetime import datetime, timedelta, timezone
import io
import json
from unittest.mock import Mock, patch

from tests.support import OfflineCase
import main as collector
from src.adapters.base_adapter import AdapterConfig, AdapterError, RawPayload
from src.models import CourseTask
from src.parsers.learn_html import LearnHtmlParser, parse_datetime_hint
from src.pipeline import DeduplicationStore, PipelineError, filter_new_records, upsert_jsonl_by_raw_id
from scripts.export_attachments import build_learn_candidates, unique_path


def task(raw_id="synthetic-id", **changes):
    fields = dict(source="learn", raw_id=raw_id, course_name="合成课程", title="合成作业", content="合成内容", task_type="homework",
                  status="unsubmitted", completed=False, created_at=datetime(2026, 3, 1, tzinfo=timezone(timedelta(hours=8))))
    fields.update(changes)
    return CourseTask(**fields)


class CourseTests(OfflineCase):
    def sync(self, courses, semester="2025-2026-2"):
        adapter = Mock()
        adapter.config = AdapterConfig(source="learn", base_url="https://synthetic.invalid")
        adapter.require.return_value = "https://synthetic.invalid"
        calls = []
        def fetch(endpoint, *, raw_id, **kwargs):
            calls.append(endpoint)
            payload = {"resultList": courses} if "loadCourseBySemesterId" in endpoint else {"resultList": [{"id": "notice", "title": "合成通知", "content": "课程公告"}]}
            return RawPayload(source="learn", raw_id=raw_id, content=json.dumps(payload), content_type="application/json")
        adapter.fetch_endpoint.side_effect = fetch
        spec = lambda course: [{"name": "notice", "task_type": "notice", "endpoint": "/synthetic/notices"}]
        with patch.object(collector, "default_learn_business_specs", side_effect=spec), patch.object(collector, "sync_learn_courseware_files", return_value=([], [])):
            _, records = collector.sync_learn_business(adapter, LearnHtmlParser(), semester)
        return records, calls

    def test_normal_courses_keep_course_mapping(self):
        records, _ = self.sync([{"wlkcid": "course-a", "kcm": "合成数学"}, {"wlkcid": "course-b", "kcm": "合成物理"}])
        self.assertEqual([r.course_name for r in records], ["合成数学", "合成物理"])
        self.assertEqual(len({r.raw_id for r in records}), 2)

    def test_empty_course_list(self):
        records, calls = self.sync([])
        self.assertEqual(records, [])
        self.assertEqual(len(calls), 1)

    def test_missing_id_skipped_name_defaults(self):
        records, _ = self.sync([{}, None, 7, {"id": "synthetic"}])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].course_name, "Unknown Course")

    def test_semester_is_sent_to_actual_course_endpoint(self):
        for semester in ["2025-2026-1", "2025-2026-2"]:
            _, calls = self.sync([], semester)
            self.assertIn("/" + semester + "/", calls[0])

    def test_duplicate_courses_do_not_fetch_twice(self):
        records, calls = self.sync([{"id": "synthetic"}, {"id": "synthetic"}])
        self.assertEqual(len(records), 1)
        self.assertEqual(calls.count("/synthetic/notices"), 1)

    def test_changed_list_structure_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "resultList"):
            self.sync({"unexpected": []})

    def test_invalid_current_semester_response(self):
        adapter = Mock()
        adapter.fetch_endpoint.return_value = RawPayload(source="learn", raw_id="synthetic", content='{"result":{}}', content_type="application/json")
        with self.assertRaisesRegex(ValueError, "xnxq"):
            collector.sync_learn_business(adapter, LearnHtmlParser())


class HomeworkTests(OfflineCase):
    def parse(self, **item):
        return LearnHtmlParser().parse(json.dumps({"resultList": [{"id": "hw1", "bt": "合成作业", **item}]}), {"task_type": "homework", "course_name": "合成课程"})[0]

    def test_submitted_unsubmitted_and_graded(self):
        for upstream, status, done in [("未交", "unsubmitted", False), ("已交", "submitted_ungraded", True), ("已批改", "graded", True)]:
            item = self.parse(zt=upstream)
            self.assertEqual((item.status, item.completed), (status, done))

    def test_missing_deadline_is_unknown_not_fabricated(self):
        self.assertIsNone(self.parse().ddl)

    def test_localized_deadline_and_html_content(self):
        item = self.parse(jzsjStr="2026年3月10日 09:30", zynrStr="&lt;p&gt;合成说明&lt;/p&gt;")
        self.assertEqual(item.content, "合成说明")
        self.assertEqual(item.ddl.hour, 9)
        self.assertEqual(item.ddl.utcoffset(), timedelta(hours=8))

    def test_explicit_iso_timezone_and_seconds_preserved(self):
        item = self.parse(ddl="2026-03-10T09:30:45+00:00")
        self.assertEqual(item.ddl, datetime(2026, 3, 10, 9, 30, 45, tzinfo=timezone.utc))

    def test_bad_dates_and_bad_timezone_not_silently_accepted(self):
        for value in ["not-a-date", "2026-02-31 10:00", "2026-03-10T10:00:00+25:00"]:
            self.assertIsNone(parse_datetime_hint(value))

    def test_date_only_retains_end_of_day_default(self):
        self.assertEqual(parse_datetime_hint("2026-03-10").strftime("%H:%M"), "23:59")

    def test_detail_enrichment_uses_real_merge_and_deduplicates_urls(self):
        adapter = Mock()
        adapter.require.return_value = "https://learn.tsinghua.edu.cn"
        adapter.fetch_endpoint.side_effect = [
            RawPayload(source="learn", raw_id="detail", content='{"msg":"<p>合成详细说明</p>"}', content_type="application/json"),
            RawPayload(source="learn", raw_id="view", content='<a href="/b/wlxt/kczy/zy/student/downloadFile/course-a/f1">合成附件.pdf</a>', content_type="text/html"),
        ]
        record = task("list_hw1", attachments=[{"name": "合成附件.pdf", "download_url": "https://learn.tsinghua.edu.cn/b/wlxt/kczy/zy/student/downloadFile/course-a/f1"}])
        _, records = collector.enrich_learn_homework_records(adapter, [record], {"resultList": [{"zyid": "hw1", "wlkcid": "course-a", "xszyid": "submission-a"}]})
        self.assertEqual(records[0].content, "合成详细说明")
        self.assertEqual(len(records[0].attachments), 1)
        self.assertEqual(adapter.fetch_endpoint.call_count, 2)

    def test_semester_filter_has_explicit_clock(self):
        start = collector.learn_semester_start("2025-2026-2")
        records = [task("old", ddl=start-timedelta(days=1)), task("pending", ddl=start+timedelta(days=5)), task("done", ddl=start+timedelta(days=5), completed=True)]
        result = collector.filter_learn_records_for_semester(records, start, now=start+timedelta(days=10))
        self.assertEqual([r.raw_id for r in result], ["pending"])


class StorageTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.output = self.root / "collector.jsonl"
        self.db = self.root / "state.db"

    def rows(self):
        return [json.loads(line) for line in self.output.read_text().splitlines()]

    def test_database_fingerprint_idempotent_and_source_scoped(self):
        store = DeduplicationStore(self.db)
        self.assertEqual(len(filter_new_records([task()], store)), 1)
        self.assertEqual(filter_new_records([task()], store), [])
        self.assertEqual(len(filter_new_records([task(source="mail")], store)), 1)

    def test_same_name_different_ids_not_collapsed(self):
        upsert_jsonl_by_raw_id([task("a", content="版本一"), task("b", content="版本二")], self.output)
        self.assertEqual(len(self.rows()), 2)

    def test_duplicate_input_counts_unique_records(self):
        self.assertEqual(upsert_jsonl_by_raw_id([task(), task()], self.output), 1)
        self.assertEqual(len(self.rows()), 1)

    def test_richer_old_content_does_not_freeze_new_status(self):
        upsert_jsonl_by_raw_id([task(content="合成的较长详细说明")], self.output)
        self.assertEqual(upsert_jsonl_by_raw_id([task(content="短", status="submitted_ungraded", completed=True)], self.output), 0)
        self.assertTrue(self.rows()[0]["completed"])
        self.assertEqual(self.rows()[0]["status"], "submitted_ungraded")

    def test_atomic_replace_failure_preserves_old_output(self):
        upsert_jsonl_by_raw_id([task("a")], self.output)
        original = self.output.read_bytes()
        with patch("src.security.os.replace", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError): upsert_jsonl_by_raw_id([task("b")], self.output)
        self.assertEqual(self.output.read_bytes(), original)
        upsert_jsonl_by_raw_id([task("b")], self.output)
        self.assertEqual(len(self.rows()), 2)

    def test_cursor_persists_across_store_instances(self):
        DeduplicationStore(self.db).set_state("mail", "last_uid", 7)
        self.assertEqual(DeduplicationStore(self.db).get_int_state("mail", "last_uid"), 7)

    def test_invalid_cursor_fails_explicitly(self):
        store = DeduplicationStore(self.db)
        store.set_state("mail", "last_uid", "bad")
        with self.assertRaises(PipelineError): store.get_int_state("mail", "last_uid")

    def test_interrupted_mail_output_does_not_advance_cursor_or_lose_retry(self):
        message = "Subject: synthetic course homework\r\nContent-Type: text/plain; charset=utf-8\r\n\r\ncourse homework synthetic"
        payload = RawPayload(source="mail", raw_id="mail_uid_7", content=message, content_type="message/rfc822", metadata={"uid": 7, "raw_id": "mail_uid_7"})
        adapter = Mock()
        adapter.fetch_raw.return_value = [payload]
        args = argparse.Namespace(db_path=str(self.db), output=str(self.output), mailbox="INBOX", criteria="ALL", limit=10)
        with patch.object(collector, "MailAdapter", return_value=adapter):
            with patch("src.security.os.replace", side_effect=OSError("synthetic disk failure")):
                with self.assertRaises(OSError): collector.sync_channel("mail", args)
            self.assertEqual(DeduplicationStore(self.db).get_int_state("mail", "last_uid", 0), 0)
            result = collector.sync_channel("mail", args)
            self.assertEqual((result.parsed_count, result.fresh_count), (1, 1))
            self.assertEqual(DeduplicationStore(self.db).get_int_state("mail", "last_uid"), 7)
            collector.sync_channel("mail", args)
        self.assertEqual(len(self.rows()), 1)
        adapter.close.assert_called()

    def test_retry_after_transient_failure_and_partial_channel_failure(self):
        args = argparse.Namespace(retries=2, retry_delay=0)
        success = collector.SyncResult("learn", 1, 1, 1, self.output)
        with patch.object(collector, "sync_channel", side_effect=[AdapterError("synthetic"), success]), patch.object(collector.time, "sleep"):
            self.assertEqual(collector.run_with_retries("learn", args), success)
        def channel(name, args):
            if name == "mail": raise AdapterError("synthetic")
            return collector.SyncResult(name, 1, 1, 1, self.output)
        output = io.StringIO()
        with patch.object(collector, "sync_channel", side_effect=channel), patch.object(collector, "load_project_env"), patch.object(collector, "configure_logging"), patch("sys.argv", ["main.py", "--channel", "all", "--allow-network", "--retries", "1"]), patch("sys.stdout", output), self.assertLogs(level="ERROR") as logs:
            self.assertEqual(collector.main(), 1)
        self.assertEqual(output.getvalue().count("[OK]"), 2)
        self.assertEqual(output.getvalue().count("[FAIL]"), 1)
        self.assertIn("channel=mail", " ".join(logs.output))

    def test_cursor_commit_failure_replays_already_published_output(self):
        payload = RawPayload(source="mail", raw_id="mail_uid_8", content="Subject: course homework\r\n\r\nsynthetic course homework", content_type="message/rfc822", metadata={"uid": 8, "raw_id": "mail_uid_8"})
        adapter = Mock()
        adapter.fetch_raw.return_value = [payload]
        args = argparse.Namespace(db_path=str(self.db), output=str(self.output), mailbox="INBOX", criteria="ALL", limit=10)
        with patch.object(collector, "MailAdapter", return_value=adapter):
            with patch.object(DeduplicationStore, "set_state", side_effect=PipelineError("synthetic cursor failure")):
                with self.assertRaises(PipelineError): collector.sync_channel("mail", args)
            self.assertEqual(len(self.rows()), 1)
            self.assertEqual(DeduplicationStore(self.db).get_int_state("mail", "last_uid", 0), 0)
            self.assertEqual(collector.sync_channel("mail", args).fresh_count, 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(DeduplicationStore(self.db).get_int_state("mail", "last_uid"), 8)


class AttachmentMetadataTests(OfflineCase):
    def candidates(self, attachments):
        return build_learn_candidates([{"source": "learn", "raw_id": "synthetic", "task_type": "file", "attachments": attachments}], base_url="https://learn.tsinghua.edu.cn", already_exported=set(), include_homework=False, include_notices=True, prefer_course_files=True)

    def test_normal_and_missing_link(self):
        items = self.candidates([{"name": "合成.pdf", "download_url": "/f1.pdf"}, {"name": "缺失.pdf"}])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://learn.tsinghua.edu.cn/f1.pdf")

    def test_unsafe_link_rejected_not_fetched(self):
        self.assertEqual(self.candidates([{"name": "合成.pdf", "download_url": "http://127.0.0.1/a.pdf"}]), [])

    def test_duplicate_url_candidate_only_once(self):
        entry = {"name": "合成.pdf", "download_url": "/f1.pdf"}
        self.assertEqual(len(self.candidates([entry, entry])), 1)

    def test_same_name_different_versions_remain_distinct_in_current_batch(self):
        items = self.candidates([{"name": "合成.pdf", "download_url": "/v1.pdf"}, {"name": "合成.pdf", "download_url": "/v2.pdf"}])
        self.assertEqual(len(items), 2)
        path = self.root / "合成.pdf"
        path.write_bytes(b"synthetic version 1")
        other = unique_path(path)
        self.assertNotEqual(other, path)
        other.write_bytes(b"synthetic version 2")
        self.assertEqual(path.read_bytes(), b"synthetic version 1")
