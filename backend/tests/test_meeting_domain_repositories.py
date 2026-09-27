"""Unit tests for meeting-result SQLAlchemy repositories."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_domain_repositories():
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))

    modules = [
        importlib.import_module(f"app.repositories.{module_name}")
        for module_name in (
            "summary_repository",
            "task_repository",
            "decision_repository",
            "followup_repository",
        )
    ]
    return tuple(
        getattr(module, class_name)
        for module, class_name in zip(
            modules,
            ("SummaryRepository", "TaskRepository", "DecisionRepository", "FollowupRepository"),
        )
    )


class MeetingDomainRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        (
            self.SummaryRepository,
            self.TaskRepository,
            self.DecisionRepository,
            self.FollowupRepository,
        ) = _load_domain_repositories()
        self.session = MagicMock(spec=AsyncSession)
        self.session.flush = AsyncMock()
        self.session.execute = AsyncMock()

        from shared.database.models.decision import Decision
        from shared.database.models.followup import Followup, FollowupStatus
        from shared.database.models.summary import Summary
        from shared.database.models.task import Task, TaskStatus

        self.Summary = Summary
        self.Task = Task
        self.TaskStatus = TaskStatus
        self.Decision = Decision
        self.Followup = Followup
        self.FollowupStatus = FollowupStatus

    def _assert_no_transaction_control(self) -> None:
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def _assert_value_in_statement(self, value: object) -> None:
        statement = self.session.execute.await_args.args[0]
        self.assertIn(value, statement.compile().params.values())

    def _meeting_scoped_rows(self, rows: list[object]) -> object:
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        self.session.execute.return_value = result
        return result

    def _single_row_result(self, row: object | None) -> object:
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        self.session.execute.return_value = result
        return result

    def test_summary_create_adds_flushes_and_does_not_commit(self) -> None:
        summary = self.Summary(
            meeting_id=uuid.uuid4(), content="Summary", key_topics=["planning"]
        )
        repository = self.SummaryRepository(self.session)

        created = asyncio.run(repository.create(summary))

        self.assertIs(created, summary)
        self.session.add.assert_called_once_with(summary)
        self.session.flush.assert_awaited_once()
        self._assert_no_transaction_control()

    def test_summary_get_by_id_filters_by_id(self) -> None:
        summary = self.Summary(
            id=uuid.uuid4(), meeting_id=uuid.uuid4(), content="Summary", key_topics=[]
        )
        self._single_row_result(summary)
        repository = self.SummaryRepository(self.session)

        found = asyncio.run(repository.get_by_id(summary.id))

        self.assertIs(found, summary)
        self.assertIn("WHERE summaries.id", str(self.session.execute.await_args.args[0]))
        self._assert_value_in_statement(summary.id)
        self._assert_no_transaction_control()

    def test_summary_list_is_meeting_scoped_and_ordered_by_version(self) -> None:
        meeting_id = uuid.uuid4()
        summaries = [
            self.Summary(meeting_id=meeting_id, content="v1", key_topics=[], version=1),
            self.Summary(meeting_id=meeting_id, content="v2", key_topics=[], version=2),
        ]
        self._meeting_scoped_rows(summaries)
        repository = self.SummaryRepository(self.session)

        found = asyncio.run(repository.list_by_meeting_id(meeting_id))

        self.assertEqual(found, summaries)
        statement = self.session.execute.await_args.args[0]
        sql = str(statement)
        self.assertIn("WHERE summaries.meeting_id", sql)
        self.assertIn("ORDER BY summaries.version ASC, summaries.id ASC", sql)
        self._assert_value_in_statement(meeting_id)
        self._assert_no_transaction_control()

    def test_summary_latest_query_filters_meeting_and_orders_descending(self) -> None:
        meeting_id = uuid.uuid4()
        latest = self.Summary(
            meeting_id=meeting_id, content="v3", key_topics=[], version=3
        )
        self._single_row_result(latest)
        repository = self.SummaryRepository(self.session)

        found = asyncio.run(repository.get_latest_by_meeting_id(meeting_id))

        self.assertIs(found, latest)
        statement = self.session.execute.await_args.args[0]
        self.assertIn("WHERE summaries.meeting_id", str(statement))
        self.assertIn("ORDER BY summaries.version DESC", str(statement))
        self.assertEqual(statement._limit_clause.value, 1)
        self._assert_value_in_statement(meeting_id)
        self._assert_no_transaction_control()

    def test_task_create_and_update_flush_without_transaction_control(self) -> None:
        task = self.Task(meeting_id=uuid.uuid4(), title="Send notes", assignee_id=None)
        repository = self.TaskRepository(self.session)

        created = asyncio.run(repository.create(task))
        self.assertIs(created, task)
        self.session.add.assert_called_once_with(task)
        self.session.flush.assert_awaited_once()
        self._assert_no_transaction_control()

        self.session.add.reset_mock()
        self.session.flush.reset_mock()
        task.title = "Send updated notes"
        updated = asyncio.run(repository.update(task))
        self.assertIs(updated, task)
        self.session.add.assert_called_once_with(task)
        self.session.flush.assert_awaited_once()
        self._assert_no_transaction_control()

    def test_task_get_by_id_filters_by_id(self) -> None:
        task = self.Task(id=uuid.uuid4(), meeting_id=uuid.uuid4(), title="Send notes")
        self._single_row_result(task)
        repository = self.TaskRepository(self.session)

        found = asyncio.run(repository.get_by_id(task.id))

        self.assertIs(found, task)
        self.assertIn("WHERE tasks.id", str(self.session.execute.await_args.args[0]))
        self._assert_value_in_statement(task.id)
        self._assert_no_transaction_control()

    def test_task_list_filters_meeting_and_optional_status_with_stable_order(self) -> None:
        meeting_id = uuid.uuid4()
        task = self.Task(meeting_id=meeting_id, title="Send notes")
        self._meeting_scoped_rows([task])
        repository = self.TaskRepository(self.session)

        found = asyncio.run(
            repository.list_by_meeting_id(meeting_id, status=self.TaskStatus.OPEN)
        )

        self.assertEqual(found, [task])
        statement = self.session.execute.await_args.args[0]
        sql = str(statement)
        self.assertIn("tasks.meeting_id", sql)
        self.assertIn("tasks.status", sql)
        self.assertIn("ORDER BY tasks.created_at DESC, tasks.id DESC", sql)
        self._assert_value_in_statement(meeting_id)
        self._assert_value_in_statement(self.TaskStatus.OPEN)
        self._assert_no_transaction_control()

    def test_decision_create_adds_and_flushes(self) -> None:
        decision = self.Decision(
            id=uuid.uuid4(),
            meeting_id=uuid.uuid4(),
            statement="Ship the release",
            participants=[],
        )
        repository = self.DecisionRepository(self.session)

        created = asyncio.run(repository.create(decision))

        self.assertIs(created, decision)
        self.session.add.assert_called_once_with(decision)
        self.session.flush.assert_awaited_once()
        self._assert_no_transaction_control()

    def test_decision_get_by_id_filters_by_id(self) -> None:
        decision = self.Decision(
            id=uuid.uuid4(),
            meeting_id=uuid.uuid4(),
            statement="Ship the release",
            participants=[],
        )
        self._single_row_result(decision)
        repository = self.DecisionRepository(self.session)

        found = asyncio.run(repository.get_by_id(decision.id))

        self.assertIs(found, decision)
        self.assertIn("WHERE decisions.id", str(self.session.execute.await_args.args[0]))
        self._assert_value_in_statement(decision.id)
        self._assert_no_transaction_control()

    def test_decision_list_filters_meeting_and_has_deterministic_order(self) -> None:
        meeting_id = uuid.uuid4()
        decision = self.Decision(
            meeting_id=meeting_id, statement="Ship the release", participants=[]
        )
        self._meeting_scoped_rows([decision])
        repository = self.DecisionRepository(self.session)

        found = asyncio.run(repository.list_by_meeting_id(meeting_id))

        self.assertEqual(found, [decision])
        statement = self.session.execute.await_args.args[0]
        self.assertIn("WHERE decisions.meeting_id", str(statement))
        self.assertIn(
            "ORDER BY decisions.created_at ASC, decisions.id ASC", str(statement)
        )
        self._assert_value_in_statement(meeting_id)
        self._assert_no_transaction_control()

    def test_followup_create_adds_and_flushes(self) -> None:
        followup = self.Followup(
            id=uuid.uuid4(),
            meeting_id=uuid.uuid4(),
            subject="Meeting recap",
            body_html="<p>Recap</p>",
            recipients=["person@example.com"],
        )
        repository = self.FollowupRepository(self.session)

        created = asyncio.run(repository.create(followup))

        self.assertIs(created, followup)
        self.session.add.assert_called_once_with(followup)
        self.session.flush.assert_awaited_once()
        self._assert_no_transaction_control()

    def test_followup_update_adds_and_flushes_without_transaction_control(self) -> None:
        followup = self.Followup(
            id=uuid.uuid4(),
            meeting_id=uuid.uuid4(),
            subject="Meeting recap",
            body_html="<p>Recap</p>",
            recipients=[],
        )
        repository = self.FollowupRepository(self.session)

        updated = asyncio.run(repository.update(followup))

        self.assertIs(updated, followup)
        self.session.add.assert_called_once_with(followup)
        self.session.flush.assert_awaited_once()
        self._assert_no_transaction_control()

    def test_followup_get_by_id_filters_by_id(self) -> None:
        followup = self.Followup(
            id=uuid.uuid4(),
            meeting_id=uuid.uuid4(),
            subject="Meeting recap",
            body_html="<p>Recap</p>",
            recipients=[],
        )
        self._single_row_result(followup)
        repository = self.FollowupRepository(self.session)

        found = asyncio.run(repository.get_by_id(followup.id))

        self.assertIs(found, followup)
        self.assertIn("WHERE followups.id", str(self.session.execute.await_args.args[0]))
        self._assert_value_in_statement(followup.id)
        self._assert_no_transaction_control()

    def test_followup_list_filters_meeting_and_status_with_stable_order(self) -> None:
        meeting_id = uuid.uuid4()
        followup = self.Followup(
            meeting_id=meeting_id,
            subject="Meeting recap",
            body_html="<p>Recap</p>",
            recipients=[],
        )
        self._meeting_scoped_rows([followup])
        repository = self.FollowupRepository(self.session)

        found = asyncio.run(
            repository.list_by_meeting_id(
                meeting_id, status=self.FollowupStatus.DRAFT
            )
        )

        self.assertEqual(found, [followup])
        statement = self.session.execute.await_args.args[0]
        sql = str(statement)
        self.assertIn("followups.meeting_id", sql)
        self.assertIn("followups.status", sql)
        self.assertIn("ORDER BY followups.created_at DESC, followups.id DESC", sql)
        self._assert_value_in_statement(meeting_id)
        self._assert_value_in_statement(self.FollowupStatus.DRAFT)
        self._assert_no_transaction_control()


if __name__ == "__main__":
    unittest.main()
