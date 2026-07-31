"""Payment-lane exceptions.

The payment package uses explicit exception types so API composition can distinguish
policy denials, replay attempts, malformed protocol input, ambiguous execution, and
receipt-verification failures without inspecting error strings.
"""

from __future__ import annotations

from enum import Enum


class SubmissionStatus(str, Enum):
    """What an executor failure proves about provider submission."""

    NOT_SUBMITTED = "not_submitted"
    AMBIGUOUS = "ambiguous"


class PaymentError(RuntimeError):
    """Base class for payment-lane failures."""


class PaymentValidationError(PaymentError, ValueError):
    """A payment intent, policy, address, or receipt field is malformed."""


class PaymentPolicyDenied(PaymentError):
    """A deterministic payment policy denied an otherwise well-formed intent."""

    def __init__(self, reason_code: str, explanation: str) -> None:
        super().__init__(f"{reason_code}: {explanation}")
        self.reason_code = reason_code
        self.explanation = explanation


class PaymentReplayError(PaymentError):
    """An idempotency key, x402 identifier, or transaction hash was replayed."""


class X402ParseError(PaymentValidationError):
    """An x402 payment requirement could not be parsed safely."""


class CircleExecutionError(PaymentError):
    """Circle execution failed or returned an unsafe/ambiguous response."""

    def __init__(
        self,
        message: str,
        *,
        terminal: bool = False,
        returncode: int | None = None,
        reason_code: str = "circle_execution_ambiguous",
        submission_status: SubmissionStatus | str = SubmissionStatus.AMBIGUOUS,
    ) -> None:
        super().__init__(message)
        self.terminal = terminal
        self.returncode = returncode
        self.reason_code = reason_code
        self.submission_status = SubmissionStatus(submission_status)

    @property
    def reconciliation_required(self) -> bool:
        """Whether settlement must be reconciled before any new submission."""

        return (
            not self.terminal
            and self.submission_status is SubmissionStatus.AMBIGUOUS
        )

    @property
    def proven_not_submitted(self) -> bool:
        """Whether the failure safely proves Circle did not receive a transfer."""

        return self.submission_status is SubmissionStatus.NOT_SUBMITTED


class ReceiptVerificationError(PaymentError):
    """Execution evidence did not prove the intended payment."""
