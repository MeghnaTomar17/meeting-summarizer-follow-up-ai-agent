"""Unit tests for meeting-result domain services."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_domain_services():
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))

    modules = [
        importlib.import_module(f"app.services.{module_name}")
        for module_name in (
            "summary_service",
            "task_service",
            "decision_service",
            "followup_service",
        )
    ]
    return tuple(
        getattr(module, class_name)
        for module, class_name in zip(
            modules,
            ("SummaryService", "TaskService", "DecisionService", "FollowUpService"),
        )
    )


class _ConstraintViolation:
    constraint_name = "uq_summaries_meeting_version"


class MeetingDomainServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        (
            self.SummaryService,
            self.TaskService,
            self.DecisionService,
            self.FollowUpService,
        ) = _load_domain_services()

        from app.repositories.decision_repository import DecisionRepository
        from app.repositories.followup_repository import FollowupRepository
        from app.repositories.summary_repository import SummaryRepository
        from app.repositories.task_repository import TaskRepository
        from app.services.meeting_service import MeetingService
        from shared.database.models.decision import Decision
        from shared.database.models.followup import Followup, FollowupStatus
        from shared.database.models.meeting import Meeting
        from shared.database.models.summary import Summary
        from shared.database.models.task import Task, TaskStatus
        from shared.exceptions.common import (
            ConflictError,
            ForbiddenError,
            NotFoundError,
        )
        from shared.exceptions.common import ValidationError as AppValidationError
        from shared.schemas.decision import DecisionBase
        from shared.schemas.followup import (
            FollowupBase,
            FollowupStatus as SchemaFollowupStatus,
            FollowupUpdate,
        )
        from shared.schemas.summary import SummaryBase
        from shared.schemas.task import TaskBase, TaskStatus as SchemaTaskStatus
        from shared.schemas.task import TaskUpdate

        self.MeetingService = MeetingService
        self.Summary = Summary
        self.Task = Task
        self.TaskStatus = TaskStatus
        self.Decision = Decision
        self.Followup = Followup
        self.FollowupStatus = FollowupStatus
        self.Meeting = Meeting
        self.ConflictError = ConflictError
        self.ForbiddenError = ForbiddenError
        self.NotFoundError = NotFoundError
        self.AppValidationError = AppValidationError
        self.SummaryBase = SummaryBase
        self.TaskBase = TaskBase
        self.SchemaTaskStatus = SchemaTaskStatus
        self.TaskUpdate = TaskUpdate
        self.DecisionBase = DecisionBase
        self.FollowupBase = FollowupBase
        self.SchemaFollowupStatus = SchemaFollowupStatus
        self.FollowupUpdate = FollowupUpdate

        self.session = MagicMock(spec=AsyncSession)
        self.session.commit = AsyncMock()
        self.summary_repository = MagicMock(spec=SummaryRepository)
        self.task_repository = MagicMock(spec=TaskRepository)
        self.decision_repository = MagicMock(spec=DecisionRepository)
        self.followup_repository = MagicMock(spec=FollowupRepository)
        self.meeting_service = MagicMock(spec=MeetingService)
        self.meeting = self._meeting()
        self.meeting_service.require_owned_meeting = AsyncMock(
            return_value=self.meeting
        )

        self.summary_service = self.SummaryService(
            self.session, self.summary_repository, self.meeting_service
        )
        self.task_service = self.TaskService(
            self.session, self.task_repository, self.meeting_service
        )
        self.decision_service = self.DecisionService(
            self.session, self.decision_repository, self.meeting_service
        )
        self.followup_service = self.FollowUpService(
            self.session, self.followup_repository, self.meeting_service
        )
        self.user_id = uuid.uuid4()
        self.now = datetime.now(timezone.utc)

    def _meeting(self, *, owner_id: uuid.UUID | None = None) -> object:
        return self.Meeting(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            created_by=owner_id or uuid.uuid4(),
            title="Planning",
            participants=[],
        )

    def _summary(self, meeting_id: uuid.UUID | None = None, *, version: int = 1) -> object:
        return self.Summary(
            id=uuid.uuid4(),
            meeting_id=meeting_id or self.meeting.id,
            content="Decisions and next steps.",
            key_topics=["planning"],
            model_provider="provider",
            model_name="model",
            version=version,
            created_at=self.now,
        )

    def _task(self, meeting_id: uuid.UUID | None = None) -> object:
        return self.Task(
            id=uuid.uuid4(),
            meeting_id=meeting_id or self.meeting.id,
            title="Send notes",
            description="Email the recap",
            assignee_id=None,
            due_at=None,
            status=self.TaskStatus.OPEN,
            created_at=self.now,
            updated_at=self.now,
        )

    def _decision(self, meeting_id: uuid.UUID | None = None) -> object:
        return self.Decision(
            id=uuid.uuid4(),
            meeting_id=meeting_id or self.meeting.id,
            statement="Ship the release",
            context="After QA",
            participants=["Alex"],
            created_at=self.now,
        )

    def _followup(self, meeting_id: uuid.UUID | None = None) -> object:
        return self.Followup(
            id=uuid.uuid4(),
            meeting_id=meeting_id or self.meeting.id,
            subject="Meeting recap",
            body_html="<p>Recap</p>",
            recipients=["alex@example.com"],
            status=self.FollowupStatus.DRAFT,
            scheduled_at=None,
            sent_at=None,
            created_at=self.now,
        )

    def _assert_no_commit(self) -> None:
        self.session.commit.assert_not_awaited()

    def test_summary_creation_uses_authoritative_meeting_and_commits_once(self) -> None:
        summary = self._summary(version=2)
        self.summary_repository.create.return_value = summary
        payload = self.SummaryBase(
            meeting_id=str(uuid.uuid4()),
            content=summary.content,
            key_topics=summary.key_topics,
            model_provider=summary.model_provider,
            model_name=summary.model_name,
        )

        result = asyncio.run(
            self.summary_service.create_summary(payload, self.user_id, version=2)
        )

        submitted = self.summary_repository.create.await_args.args[0]
        self.assertEqual(submitted.meeting_id, self.meeting.id)
        self.assertEqual(submitted.version, 2)
        self.assertEqual(result.version, 2)
        self.meeting_service.require_owned_meeting.assert_awaited_once_with(
            payload.meeting_id, self.user_id
        )
        self.session.commit.assert_awaited_once()

    def test_summary_rejects_nonpositive_version_without_writes(self) -> None:
        payload = self.SummaryBase(meeting_id=str(self.meeting.id), content="Summary")

        with self.assertRaises(self.AppValidationError):
            asyncio.run(self.summary_service.create_summary(payload, self.user_id, version=0))

        self.summary_repository.create.assert_not_awaited()
        self._assert_no_commit()

    def test_duplicate_summary_version_maps_to_conflict_without_commit(self) -> None:
        payload = self.SummaryBase(meeting_id=str(self.meeting.id), content="Summary")
        self.summary_repository.create.side_effect = IntegrityError(
            "insert summaries", {}, _ConstraintViolation()
        )

        with self.assertRaises(self.ConflictError):
            asyncio.run(self.summary_service.create_summary(payload, self.user_id, version=1))

        self._assert_no_commit()

    def test_summary_get_list_and_latest_are_meeting_owned(self) -> None:
        summary = self._summary(version=3)
        self.summary_repository.get_by_id.return_value = summary
        self.summary_repository.list_by_meeting_id.return_value = [summary]
        self.summary_repository.get_latest_by_meeting_id.return_value = summary

        found = asyncio.run(self.summary_service.get_summary(str(summary.id), self.user_id))
        rows = asyncio.run(
            self.summary_service.list_summaries(str(self.meeting.id), self.user_id)
        )
        latest = asyncio.run(
            self.summary_service.get_latest_summary(str(self.meeting.id), self.user_id)
        )

        self.assertEqual(found.id, str(summary.id))
        self.assertEqual([row.version for row in rows], [3])
        self.assertEqual(latest.version, 3)
        self.summary_repository.list_by_meeting_id.assert_awaited_once_with(self.meeting.id)
        self.summary_repository.get_latest_by_meeting_id.assert_awaited_once_with(
            self.meeting.id
        )
        self._assert_no_commit()

    def test_summary_missing_resources_do_not_commit(self) -> None:
        self.summary_repository.get_by_id.return_value = None
        with self.assertRaises(self.NotFoundError):
            asyncio.run(self.summary_service.get_summary(str(uuid.uuid4()), self.user_id))

        self.summary_repository.get_by_id.return_value = self._summary()
        self.summary_repository.get_latest_by_meeting_id.return_value = None
        with self.assertRaises(self.NotFoundError):
            asyncio.run(
                self.summary_service.get_latest_summary(str(self.meeting.id), self.user_id)
            )
        self._assert_no_commit()

    def test_task_creation_maps_optional_assignee_and_commits_once(self) -> None:
        assignee_id = uuid.uuid4()
        task = self._task()
        task.assignee_id = assignee_id
        self.task_repository.create.return_value = task
        payload = self.TaskBase(
            meeting_id=str(uuid.uuid4()),
            title="Send notes",
            assignee_id=str(assignee_id),
        )

        result = asyncio.run(self.task_service.create_task(payload, self.user_id))

        submitted = self.task_repository.create.await_args.args[0]
        self.assertEqual(submitted.meeting_id, self.meeting.id)
        self.assertEqual(submitted.assignee_id, assignee_id)
        self.assertEqual(result.assignee_id, str(assignee_id))
        self.session.commit.assert_awaited_once()

    def test_task_creation_rejects_invalid_assignee_without_commit(self) -> None:
        payload = self.TaskBase(
            meeting_id=str(self.meeting.id), title="Send notes", assignee_id="invalid"
        )

        with self.assertRaises(self.AppValidationError):
            asyncio.run(self.task_service.create_task(payload, self.user_id))

        self.task_repository.create.assert_not_awaited()
        self._assert_no_commit()

    def test_task_get_and_list_are_meeting_owned_and_status_filtered(self) -> None:
        task = self._task()
        task.status = self.TaskStatus.DONE
        self.task_repository.get_by_id.return_value = task
        self.task_repository.list_by_meeting_id.return_value = [task]

        found = asyncio.run(self.task_service.get_task(str(task.id), self.user_id))
        rows = asyncio.run(
            self.task_service.list_tasks(
                str(self.meeting.id), self.user_id, status=self.SchemaTaskStatus.DONE
            )
        )

        self.assertEqual(found.status, self.SchemaTaskStatus.DONE)
        self.assertEqual([row.id for row in rows], [str(task.id)])
        self.task_repository.list_by_meeting_id.assert_awaited_once_with(
            self.meeting.id, status=self.TaskStatus.DONE
        )
        self._assert_no_commit()

    def test_task_update_applies_partial_fields_and_commits_once(self) -> None:
        task = self._task()
        self.task_repository.get_by_id.return_value = task
        self.task_repository.update.return_value = task
        payload = self.TaskUpdate(status="done", description=None, due_at=None)

        result = asyncio.run(
            self.task_service.update_task(str(task.id), payload, self.user_id)
        )

        self.assertEqual(task.status, self.TaskStatus.DONE)
        self.assertIsNone(task.description)
        self.assertIsNone(task.due_at)
        self.task_repository.update.assert_awaited_once_with(task)
        self.assertEqual(result.status, self.SchemaTaskStatus.DONE)
        self.session.commit.assert_awaited_once()

    def test_task_invalid_status_and_missing_update_do_not_commit(self) -> None:
        with self.assertRaises(PydanticValidationError):
            self.TaskUpdate(status="unknown")
        with self.assertRaises(PydanticValidationError):
            self.TaskUpdate(title=None)
        self.task_repository.get_by_id.return_value = None
        with self.assertRaises(self.NotFoundError):
            asyncio.run(
                self.task_service.update_task(
                    str(uuid.uuid4()), self.TaskUpdate(title="Updated"), self.user_id
                )
            )
        self.task_repository.update.assert_not_awaited()
        self._assert_no_commit()

    def test_task_invalid_status_filter_does_not_query_or_commit(self) -> None:
        with self.assertRaises(self.AppValidationError):
            asyncio.run(
                self.task_service.list_tasks(
                    str(self.meeting.id), self.user_id, status="unknown"
                )
            )

        self.task_repository.list_by_meeting_id.assert_not_awaited()
        self._assert_no_commit()

    def test_decision_create_get_and_list_commit_only_on_create(self) -> None:
        decision = self._decision()
        self.decision_repository.create.return_value = decision
        payload = self.DecisionBase(
            meeting_id=str(uuid.uuid4()),
            statement=decision.statement,
            context=decision.context,
            participants=decision.participants,
        )

        created = asyncio.run(self.decision_service.create_decision(payload, self.user_id))
        self.assertEqual(created.id, str(decision.id))
        self.session.commit.assert_awaited_once()

        self.session.commit.reset_mock()
        self.decision_repository.get_by_id.return_value = decision
        self.decision_repository.list_by_meeting_id.return_value = [decision]
        found = asyncio.run(
            self.decision_service.get_decision(str(decision.id), self.user_id)
        )
        rows = asyncio.run(
            self.decision_service.list_decisions(str(self.meeting.id), self.user_id)
        )
        self.assertEqual(found.statement, decision.statement)
        self.assertEqual(len(rows), 1)
        self._assert_no_commit()

    def test_decision_missing_record_does_not_commit(self) -> None:
        self.decision_repository.get_by_id.return_value = None

        with self.assertRaises(self.NotFoundError):
            asyncio.run(
                self.decision_service.get_decision(str(uuid.uuid4()), self.user_id)
            )

        self._assert_no_commit()

    def test_followup_create_get_and_list(self) -> None:
        followup = self._followup()
        self.followup_repository.create.return_value = followup
        payload = self.FollowupBase(
            meeting_id=str(uuid.uuid4()),
            subject=followup.subject,
            body_html=followup.body_html,
            recipients=followup.recipients,
        )

        created = asyncio.run(self.followup_service.create_followup(payload, self.user_id))
        submitted = self.followup_repository.create.await_args.args[0]
        self.assertEqual(submitted.meeting_id, self.meeting.id)
        self.assertEqual(created.status, self.SchemaFollowupStatus.DRAFT)
        self.session.commit.assert_awaited_once()

        self.session.commit.reset_mock()
        self.followup_repository.get_by_id.return_value = followup
        self.followup_repository.list_by_meeting_id.return_value = [followup]
        found = asyncio.run(
            self.followup_service.get_followup(str(followup.id), self.user_id)
        )
        rows = asyncio.run(
            self.followup_service.list_followups(
                str(self.meeting.id), self.user_id, status=self.SchemaFollowupStatus.DRAFT
            )
        )
        self.assertEqual(found.id, str(followup.id))
        self.assertEqual(len(rows), 1)
        self.followup_repository.list_by_meeting_id.assert_awaited_once_with(
            self.meeting.id, status=self.FollowupStatus.DRAFT
        )
        self._assert_no_commit()

    def test_followup_update_and_invalid_status(self) -> None:
        followup = self._followup()
        self.followup_repository.get_by_id.return_value = followup
        self.followup_repository.update.return_value = followup

        result = asyncio.run(
            self.followup_service.update_followup(
                str(followup.id),
                self.FollowupUpdate(subject="Updated recap", status="sent"),
                self.user_id,
            )
        )

        self.assertEqual(followup.subject, "Updated recap")
        self.assertEqual(followup.status, self.FollowupStatus.SENT)
        self.assertEqual(result.status, self.SchemaFollowupStatus.SENT)
        self.followup_repository.update.assert_awaited_once_with(followup)
        self.session.commit.assert_awaited_once()

        self.session.commit.reset_mock()
        with self.assertRaises(PydanticValidationError):
            self.FollowupUpdate(status="unknown")
        with self.assertRaises(PydanticValidationError):
            self.FollowupUpdate(subject=None)
        with self.assertRaises(self.AppValidationError):
            asyncio.run(
                self.followup_service.list_followups(
                    str(self.meeting.id), self.user_id, status="unknown"
                )
            )
        self.followup_repository.list_by_meeting_id.assert_not_awaited()
        self._assert_no_commit()

    def test_followup_missing_record_does_not_commit(self) -> None:
        self.followup_repository.get_by_id.return_value = None

        with self.assertRaises(self.NotFoundError):
            asyncio.run(
                self.followup_service.get_followup(str(uuid.uuid4()), self.user_id)
            )

        self.followup_repository.update.assert_not_awaited()
        self._assert_no_commit()

    def test_foreign_meeting_owner_cannot_create_any_result(self) -> None:
        payloads_and_repositories = (
            (
                self.summary_service,
                "create_summary",
                self.SummaryBase(meeting_id=str(uuid.uuid4()), content="Summary"),
                self.summary_repository,
            ),
            (
                self.task_service,
                "create_task",
                self.TaskBase(meeting_id=str(uuid.uuid4()), title="Task"),
                self.task_repository,
            ),
            (
                self.decision_service,
                "create_decision",
                self.DecisionBase(meeting_id=str(uuid.uuid4()), statement="Decision"),
                self.decision_repository,
            ),
            (
                self.followup_service,
                "create_followup",
                self.FollowupBase(
                    meeting_id=str(uuid.uuid4()),
                    subject="Recap",
                    body_html="<p>Recap</p>",
                    recipients=["owner@example.com"],
                ),
                self.followup_repository,
            ),
        )
        for service, method_name, payload, repository in payloads_and_repositories:
            with self.subTest(service=type(service).__name__):
                self.meeting_service.require_owned_meeting.reset_mock()
                meeting_repository = MagicMock()
                meeting_repository.get_by_id = AsyncMock(
                    return_value=self._meeting(owner_id=uuid.uuid4())
                )
                service._meeting_service = self.MeetingService(
                    self.session, meeting_repository, MagicMock()
                )
                with self.assertRaises(self.ForbiddenError):
                    asyncio.run(getattr(service, method_name)(payload, self.user_id))
                repository.create.assert_not_awaited()
                self._assert_no_commit()
                service._meeting_service = self.meeting_service

    def test_foreign_meeting_owner_cannot_get_list_or_update_results(self) -> None:
        owner_id = uuid.uuid4()
        foreign_meeting = self._meeting(owner_id=owner_id)
        meeting_repository = MagicMock()
        meeting_repository.get_by_id = AsyncMock(return_value=foreign_meeting)
        real_meeting_service = self.MeetingService(
            self.session, meeting_repository, MagicMock()
        )

        summary = self._summary(foreign_meeting.id)
        task = self._task(foreign_meeting.id)
        decision = self._decision(foreign_meeting.id)
        followup = self._followup(foreign_meeting.id)
        child_reads = (
            (self.summary_service, self.summary_repository, summary, "get_summary"),
            (self.task_service, self.task_repository, task, "get_task"),
            (self.decision_service, self.decision_repository, decision, "get_decision"),
            (self.followup_service, self.followup_repository, followup, "get_followup"),
        )
        for service, repository, entity, method_name in child_reads:
            with self.subTest(operation=method_name):
                service._meeting_service = real_meeting_service
                repository.get_by_id.return_value = entity
                with self.assertRaises(self.ForbiddenError):
                    asyncio.run(getattr(service, method_name)(str(entity.id), self.user_id))

        child_lists = (
            (self.summary_service, self.summary_repository, "list_summaries"),
            (self.task_service, self.task_repository, "list_tasks"),
            (self.decision_service, self.decision_repository, "list_decisions"),
            (self.followup_service, self.followup_repository, "list_followups"),
        )
        for service, repository, method_name in child_lists:
            with self.subTest(operation=method_name):
                service._meeting_service = real_meeting_service
                with self.assertRaises(self.ForbiddenError):
                    asyncio.run(
                        getattr(service, method_name)(
                            str(foreign_meeting.id), self.user_id
                        )
                    )
                repository.list_by_meeting_id.assert_not_awaited()

        for service, repository, entity, payload, method_name in (
            (
                self.task_service,
                self.task_repository,
                task,
                self.TaskUpdate(title="Changed"),
                "update_task",
            ),
            (
                self.followup_service,
                self.followup_repository,
                followup,
                self.FollowupUpdate(subject="Changed"),
                "update_followup",
            ),
        ):
            with self.subTest(operation=method_name):
                service._meeting_service = real_meeting_service
                repository.get_by_id.return_value = entity
                with self.assertRaises(self.ForbiddenError):
                    asyncio.run(
                        getattr(service, method_name)(
                            str(entity.id), payload, self.user_id
                        )
                    )
                repository.update.assert_not_awaited()

        self._assert_no_commit()

    def test_failure_before_successful_write_never_commits(self) -> None:
        payload = self.SummaryBase(meeting_id=str(self.meeting.id), content="Summary")
        self.summary_repository.create.side_effect = RuntimeError("persistence failed")

        with self.assertRaisesRegex(RuntimeError, "persistence failed"):
            asyncio.run(self.summary_service.create_summary(payload, self.user_id))

        self._assert_no_commit()


if __name__ == "__main__":
    unittest.main()
