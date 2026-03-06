from __future__ import annotations

import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from airflow.exceptions import AirflowException
from airflow.providers.amazon.aws.hooks.athena import AthenaHook
from airflow.providers.amazon.aws.operators.base_aws import AwsBaseOperator
from airflow.providers.amazon.aws.utils.mixins import aws_template_fields

if TYPE_CHECKING:
    from airflow.sdk import Context


class AthenaSparkOperator(AwsBaseOperator[AthenaHook]):
    """
    Submits an Apache Spark calculation to AWS Athena and waits for completion.

    :param session_id: The Athena session ID to run the calculation in. (templated)
    :param code_block: The Python or Scala code block to execute. (templated)
    :param workgroup: Athena workgroup used for Spark calculation.
    :param wait_for_completion: Whether to wait for the job to finish before exiting.
    :param poll_interval: Initial time (in seconds) to wait between status checks.
    :param max_poll_interval: Maximum interval (in seconds) used after backoff.
    :param max_polling_attempts: Number of status polling attempts before failing.
    :param backoff_multiplier: Exponential backoff multiplier for polling.
    :param aws_conn_id: The Airflow connection used for AWS credentials.
    """

    aws_hook_class = AthenaHook
    template_fields: Sequence[str] = aws_template_fields("session_id", "code_block", "workgroup")
    ui_color = "#e27d44"

    def __init__(
        self,
        *,
        session_id: str,
        code_block: str,
        description: str | None = None,
        workgroup: str = "primary",
        calculation_configuration: dict[str, Any] | None = None,
        client_request_token: str | None = None,
        wait_for_completion: bool = True,
        poll_interval: int = 15,
        max_poll_interval: int = 120,
        max_polling_attempts: int = 120,
        backoff_multiplier: float = 2.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.session_id = session_id
        self.code_block = code_block
        self.description = description
        self.workgroup = workgroup
        self.calculation_configuration = calculation_configuration
        self.client_request_token = client_request_token
        self.wait_for_completion = wait_for_completion
        self.poll_interval = poll_interval
        self.max_poll_interval = max_poll_interval
        self.max_polling_attempts = max_polling_attempts
        self.backoff_multiplier = backoff_multiplier
        self.calculation_execution_id: str | None = None

    def execute(self, context: Context) -> dict[str, Any]:
        if self.poll_interval <= 0:
            raise AirflowException("poll_interval must be greater than 0 seconds.")
        if self.max_poll_interval < self.poll_interval:
            raise AirflowException("max_poll_interval must be >= poll_interval.")
        if self.max_polling_attempts <= 0:
            raise AirflowException("max_polling_attempts must be greater than 0.")
        if self.backoff_multiplier < 1:
            raise AirflowException("backoff_multiplier must be >= 1.")

        self.calculation_execution_id = self.hook.start_calculation_execution(
            session_id=self.session_id,
            code_block=self.code_block,
            workgroup=self.workgroup,
            description=self.description,
            calculation_configuration=self.calculation_configuration,
            client_request_token=self.client_request_token,
        )
        self.log.info("Submitted Athena Spark calculation: %s", self.calculation_execution_id)

        if not self.wait_for_completion:
            metadata = self._build_metadata(state=None, state_change_reason=None)
            self._push_xcom_metadata(context=context, metadata=metadata)
            return metadata

        self.log.info("Polling Athena Spark calculation until a terminal state is reached.")
        sleep_seconds = float(self.poll_interval)
        started_at = time.monotonic()
        for attempt in range(1, self.max_polling_attempts + 1):
            status = self.hook.check_calculation_status(self.calculation_execution_id)
            self.log.info("Poll attempt %s/%s, current state: %s", attempt, self.max_polling_attempts, status)
            if status is None:
                raise AirflowException(
                    f"Unable to determine Athena Spark calculation state for {self.calculation_execution_id}."
                )

            if status in self.hook.CALCULATION_SUCCESS_STATES:
                metadata = self._build_metadata(state=status, state_change_reason=None)
                self._push_xcom_metadata(context=context, metadata=metadata)
                self.log.info("Athena Spark calculation completed successfully.")
                return metadata

            if status in self.hook.CALCULATION_FAILURE_STATES:
                reason = self.hook.get_calculation_state_change_reason(self.calculation_execution_id)
                metadata = self._build_metadata(state=status, state_change_reason=reason)
                self._push_xcom_metadata(context=context, metadata=metadata)
                raise AirflowException(
                    f"Athena Spark calculation failed with state {status}. "
                    f"CalculationExecutionId={self.calculation_execution_id}. "
                    f"Reason={reason or 'No reason provided by Athena.'}"
                )

            if status not in self.hook.CALCULATION_INTERMEDIATE_STATES:
                raise AirflowException(
                    f"Unexpected Athena Spark calculation state {status} for {self.calculation_execution_id}."
                )

            if (
                self.execution_timeout
                and time.monotonic() - started_at >= self.execution_timeout.total_seconds()
            ):
                raise AirflowException(
                    "Athena Spark calculation did not complete before execution_timeout expired. "
                    f"CalculationExecutionId={self.calculation_execution_id}."
                )

            if attempt < self.max_polling_attempts:
                time.sleep(sleep_seconds)
                sleep_seconds = min(self.max_poll_interval, sleep_seconds * self.backoff_multiplier)

        raise AirflowException(
            "Athena Spark calculation did not reach terminal state before max_polling_attempts was exhausted. "
            f"CalculationExecutionId={self.calculation_execution_id}."
        )

    def on_kill(self) -> None:
        """Cancels the calculation if the Airflow task is killed."""
        if self.calculation_execution_id:
            self.log.info("Task killed. Canceling Athena Spark job.")
            self.hook.stop_calculation_execution(self.calculation_execution_id)

    def _build_metadata(self, state: str | None, state_change_reason: str | None) -> dict[str, Any]:
        return {
            "calculation_execution_id": self.calculation_execution_id,
            "session_id": self.session_id,
            "workgroup": self.workgroup,
            "final_state": state,
            "state_change_reason": state_change_reason,
        }

    def _push_xcom_metadata(self, context: Context, metadata: dict[str, Any]) -> None:
        ti = context.get("ti")
        if not ti:
            return
        ti.xcom_push(key="calculation_execution_id", value=metadata["calculation_execution_id"])
        ti.xcom_push(key="athena_spark_metadata", value=metadata)
