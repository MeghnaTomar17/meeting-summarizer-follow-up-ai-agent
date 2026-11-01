"""Fail-closed token-budget interface for complete provider requests.

There is deliberately no built-in approximate counter. The installed Ollama
configuration has no verified preflight counter for the rendered chat request,
so assessments remain UNVERIFIED and production provider calls are blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.contracts import AgentKind, ModelRequest
from llm.errors import ModelBudgetExceededError, ModelBudgetUnverifiedError
from llm.model_registry import ModelMetadata


class BudgetStatus(StrEnum):
    WITHIN_BUDGET = "within_budget"
    EXCEEDS_BUDGET = "exceeds_budget"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class AgentBudgetPolicy:
    output_reserve_tokens: int | None
    safety_margin_tokens: int | None


@dataclass(frozen=True)
class TokenCount:
    value: int
    exact: bool


class CompleteRequestTokenCounter(Protocol):
    """Count a fully rendered request, including chat framing and schema rules."""

    def count_request_tokens(
        self, metadata: ModelMetadata, request: ModelRequest
    ) -> TokenCount:
        """Return the provider/model-aligned count for the exact request shape."""
        ...


@dataclass(frozen=True)
class BudgetAssessment:
    status: BudgetStatus
    provider: str
    model_id: str
    budget_scope: str
    input_tokens: int | None
    output_reserve_tokens: int | None
    safety_margin_tokens: int | None
    effective_context_limit_tokens: int | None
    reasons: tuple[str, ...] = ()


_PROCESSING_SCOPES = tuple(kind.value for kind in AgentKind)


class TokenBudgetService:
    """Assess per-agent budgets; unknown accounting can never be reported as fit."""

    def __init__(
        self,
        *,
        counter: CompleteRequestTokenCounter | None = None,
        policies: dict[str, AgentBudgetPolicy] | None = None,
    ) -> None:
        self._counter = counter
        self._policies = dict(policies) if policies is not None else {
            scope: AgentBudgetPolicy(
                output_reserve_tokens=None,
                safety_margin_tokens=None,
            )
            for scope in _PROCESSING_SCOPES
        }

    def assess(
        self, metadata: ModelMetadata, request: ModelRequest
    ) -> BudgetAssessment:
        scope = request.budget_scope or "unspecified"
        policy = self._policies.get(scope)
        reasons: list[str] = []
        if policy is None:
            reasons.append("agent_budget_policy_unconfigured")
        if metadata.effective_context_limit_tokens is None:
            reasons.append("effective_runtime_context_unverified")
        if metadata.maximum_output_tokens is None:
            reasons.append("model_output_limit_unverified")
        if metadata.published_context_limit_tokens is None:
            reasons.append("published_model_context_unverified")
        if (
            type(metadata.effective_context_limit_tokens) is not int
            or metadata.effective_context_limit_tokens <= 0
            or type(metadata.maximum_output_tokens) is not int
            or metadata.maximum_output_tokens <= 0
            or (
                metadata.published_context_limit_tokens is not None
                and (
                    type(metadata.published_context_limit_tokens) is not int
                    or metadata.published_context_limit_tokens <= 0
                    or metadata.effective_context_limit_tokens
                    > metadata.published_context_limit_tokens
                )
            )
        ):
            reasons.append("model_runtime_limits_invalid")
        if metadata.tokenizer_id is None or self._counter is None:
            reasons.append("complete_request_token_counter_unavailable")
        if policy is not None and policy.output_reserve_tokens is None:
            reasons.append("agent_output_reserve_unconfigured")
        if policy is not None and policy.safety_margin_tokens is None:
            reasons.append("agent_safety_margin_unconfigured")
        if policy is not None and (
            type(policy.output_reserve_tokens) is not int
            or policy.output_reserve_tokens <= 0
            or type(policy.safety_margin_tokens) is not int
            or policy.safety_margin_tokens < 0
            or (
                type(policy.output_reserve_tokens) is int
                and type(metadata.maximum_output_tokens) is int
                and policy.output_reserve_tokens > metadata.maximum_output_tokens
            )
        ):
            reasons.append("agent_budget_policy_invalid")

        if reasons:
            return BudgetAssessment(
                status=BudgetStatus.UNVERIFIED,
                provider=metadata.provider,
                model_id=metadata.model_id,
                budget_scope=scope,
                input_tokens=None,
                output_reserve_tokens=(
                    policy.output_reserve_tokens if policy is not None else None
                ),
                safety_margin_tokens=(
                    policy.safety_margin_tokens if policy is not None else None
                ),
                effective_context_limit_tokens=metadata.effective_context_limit_tokens,
                reasons=tuple(reasons),
            )

        assert policy is not None and self._counter is not None
        try:
            count = self._counter.count_request_tokens(metadata, request)
        except Exception:
            return BudgetAssessment(
                status=BudgetStatus.UNVERIFIED,
                provider=metadata.provider,
                model_id=metadata.model_id,
                budget_scope=scope,
                input_tokens=None,
                output_reserve_tokens=policy.output_reserve_tokens,
                safety_margin_tokens=policy.safety_margin_tokens,
                effective_context_limit_tokens=metadata.effective_context_limit_tokens,
                reasons=("token_counter_failed",),
            )
        if type(count.value) is not int or type(count.exact) is not bool:
            return BudgetAssessment(
                status=BudgetStatus.UNVERIFIED,
                provider=metadata.provider,
                model_id=metadata.model_id,
                budget_scope=scope,
                input_tokens=None,
                output_reserve_tokens=policy.output_reserve_tokens,
                safety_margin_tokens=policy.safety_margin_tokens,
                effective_context_limit_tokens=metadata.effective_context_limit_tokens,
                reasons=("token_counter_returned_invalid_result",),
            )
        if not count.exact:
            return BudgetAssessment(
                status=BudgetStatus.UNVERIFIED,
                provider=metadata.provider,
                model_id=metadata.model_id,
                budget_scope=scope,
                input_tokens=count.value,
                output_reserve_tokens=policy.output_reserve_tokens,
                safety_margin_tokens=policy.safety_margin_tokens,
                effective_context_limit_tokens=metadata.effective_context_limit_tokens,
                reasons=("token_count_is_not_exact",),
            )
        if count.value < 0:
            return BudgetAssessment(
                status=BudgetStatus.UNVERIFIED,
                provider=metadata.provider,
                model_id=metadata.model_id,
                budget_scope=scope,
                input_tokens=None,
                output_reserve_tokens=policy.output_reserve_tokens,
                safety_margin_tokens=policy.safety_margin_tokens,
                effective_context_limit_tokens=metadata.effective_context_limit_tokens,
                reasons=("token_counter_returned_invalid_count",),
            )

        status = (
            BudgetStatus.WITHIN_BUDGET
            if count.value
            + policy.output_reserve_tokens
            + policy.safety_margin_tokens
            <= metadata.effective_context_limit_tokens
            else BudgetStatus.EXCEEDS_BUDGET
        )
        return BudgetAssessment(
            status=status,
            provider=metadata.provider,
            model_id=metadata.model_id,
            budget_scope=scope,
            input_tokens=count.value,
            output_reserve_tokens=policy.output_reserve_tokens,
            safety_margin_tokens=policy.safety_margin_tokens,
            effective_context_limit_tokens=metadata.effective_context_limit_tokens,
        )

    def require_verified_fit(
        self, metadata: ModelMetadata, request: ModelRequest
    ) -> BudgetAssessment:
        """Block generation unless complete request accounting has proved a fit."""
        assessment = self.assess(metadata, request)
        if assessment.status is BudgetStatus.UNVERIFIED:
            raise ModelBudgetUnverifiedError()
        if assessment.status is BudgetStatus.EXCEEDS_BUDGET:
            raise ModelBudgetExceededError()
        return assessment


__all__ = [
    "AgentBudgetPolicy",
    "BudgetAssessment",
    "BudgetStatus",
    "CompleteRequestTokenCounter",
    "TokenBudgetService",
    "TokenCount",
]
