#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""
AthenaSparkOperator for running Apache Spark calculations in Amazon Athena.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from airflow.providers.amazon.aws.hooks.athena import AthenaHook
from airflow.providers.amazon.aws.operators.base_aws import AwsBaseOperator
from airflow.providers.amazon.aws.utils.mixins import aws_template_fields
from airflow.providers.common.compat.sdk import AirflowException

if TYPE_CHECKING:
    from airflow.sdk import Context

# Metadata keys returned by execute() and pushed to XCom for the dashboard UI.
ATHENA_SPARK_METADATA_XCOM_KEY = "athena_spark_metadata"
METADATA_KEY_CALCULATION_EXECUTION_ID = "calculation_execution_id"
METADATA_KEY_FINAL_STATE = "final_state"
METADATA_KEY_STATUS = "status"
METADATA_KEY_FAILURE_REASON = "failure_reason"
METADATA_KEY_STATE_CHANGE_REASON = "state_change_reason"
METADATA_KEY_SUBMISSION_TIME = "submission_time"
METADATA_KEY_COMPLETION_TIME = "completion_time"
METADATA_KEY_DAG_ID = "dag_id"
METADATA_KEY_TASK_ID = "task_id"
METADATA_KEY_RUN_ID = "run_id"
METADATA_KEY_MAP_INDEX = "map_index"
METADATA_KEY_SESSION_ID = "session_id"
METADATA_KEY_WORKGROUP = "workgroup"
METADATA_KEY_OUTPUT_LOCATION = "output_location"


class AthenaSparkOperator(AwsBaseOperator[AthenaHook]):
    """
    Run an Apache Spark calculation in an Amazon Athena session.

    Submits a calculation (e.g. PySpark code) via the Athena API, polls until
    the calculation reaches a terminal state (COMPLETED, FAILED, or CANCELED),
    returns execution metadata, and pushes dashboard-friendly metadata to XCom.

    .. seealso::
        - :class:`airflow.providers.amazon.aws.hooks.athena.AthenaHook`
        - `Athena for Apache Spark
          <https://docs.aws.amazon.com/athena/latest/ug/notebooks-spark-api-list.html>`__

    :param session_id: The Athena session ID in which to run the calculation. (templated)
    :param code_block: The calculation code (e.g. PySpark) to execute. (templated)
    :param description: Optional description of the calculation.
    :param client_request_token: Optional idempotency token for the submission.
    :param poll_interval: Seconds to wait between status checks. Default 30.
    :param max_polling_attempts: Maximum number of polling attempts before timing out.
        To limit total task time, use execution_timeout on the task as well.
    :param log_query: Whether to log submission details. Default True.
    :param aws_conn_id: The Airflow connection used for AWS credentials.
    :param region_name: AWS region. If not set, default boto3 behaviour is used.
    :param verify: Whether to verify SSL certificates.
    :param botocore_config: Optional botocore configuration dict.
    """

    aws_hook_class = AthenaHook
    ui_color = "#44b5e2"
    template_fields: Sequence[str] = aws_template_fields("session_id", "code_block", "description")
    template_ext: Sequence[str] = (".py",)
    template_fields_renderers = {"code_block": "python"}

    def __init__(
        self,
        *,
        session_id: str,
        code_block: str,
        description: str | None = None,
        client_request_token: str | None = None,
        poll_interval: int = 30,
        max_polling_attempts: int = 120,
        log_query: bool = True,
        aws_conn_id: str | None = "aws_default",
        region_name: str | None = None,
        verify: bool | str | None = None,
        botocore_config: dict | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            aws_conn_id=aws_conn_id,
            region_name=region_name,
            verify=verify,
            botocore_config=botocore_config,
            **kwargs,
        )
        self.session_id = session_id
        self.code_block = code_block
        self.description = description
        self.client_request_token = client_request_token
        self.poll_interval = poll_interval
        self.max_polling_attempts = max_polling_attempts
        self.log_query = log_query
        self._calculation_execution_id: str | None = None

    @property
    def _hook_parameters(self) -> dict[str, Any]:
        return {**super()._hook_parameters, "log_query": self.log_query}

    def execute(self, context: Context) -> dict[str, Any]:
        """Submit the Spark calculation, poll until terminal state, then return metadata."""
        self.log.info("Starting Athena Spark calculation in session %s", self.session_id)

        calculation_execution_id = self.hook.start_calculation(
            session_id=self.session_id,
            code_block=self.code_block,
            description=self.description,
            client_request_token=self.client_request_token,
        )
        self._calculation_execution_id = calculation_execution_id
        initial_state = self.hook.check_calculation_status(calculation_execution_id)
        self.log.info(
            "Calculation submitted. CalculationExecutionId: %s, initial state: %s",
            calculation_execution_id,
            initial_state,
        )

        if initial_state and initial_state in AthenaHook.SPARK_TERMINAL_STATES:
            return self._handle_terminal_state(
                context,
                calculation_execution_id,
                initial_state,
            )

        final_state = self._poll_until_terminal(calculation_execution_id)
        return self._handle_terminal_state(
            context,
            calculation_execution_id,
            final_state,
        )

    def _poll_until_terminal(self, calculation_execution_id: str) -> str:
        """Poll calculation status until a terminal state or timeout."""
        for attempt in range(1, self.max_polling_attempts + 1):
            if attempt > 1:
                time.sleep(self.poll_interval)
            state = self.hook.check_calculation_status(calculation_execution_id)

            if state is None:
                raise AirflowException(
                    f"Malformed or missing status for calculation {calculation_execution_id}. "
                    "Cannot continue polling."
                )

            self.log.info(
                "CalculationExecutionId: %s, current state: %s (attempt %d/%d)",
                calculation_execution_id,
                state,
                attempt,
                self.max_polling_attempts,
            )

            if state in AthenaHook.SPARK_TERMINAL_STATES:
                return state

        raise AirflowException(
            f"Polling timed out after {self.max_polling_attempts} attempts for calculation "
            f"{calculation_execution_id}. Use execution_timeout or increase max_polling_attempts."
        )

    def _handle_terminal_state(
        self,
        context: Context,
        calculation_execution_id: str,
        state: str,
    ) -> dict[str, Any]:
        """Resolve terminal state: raise on failure/cancel, build and return metadata."""
        reason = self.hook.get_calculation_state_change_reason(calculation_execution_id)
        execution_info = self.hook.get_calculation_info(calculation_execution_id)
        # Support both top-level Status and nested CalculationExecution.Status (API shape can vary)
        status = (
            execution_info.get("Status")
            or (execution_info.get("CalculationExecution") or {}).get("Status")
            or {}
        )
        submission_time = status.get("SubmissionDateTime")
        completion_time = status.get("CompletionDateTime")
        workgroup = (
            execution_info.get("WorkGroup")
            or (execution_info.get("CalculationExecution") or {}).get("WorkGroup")
            or (execution_info.get("CalculationExecution") or {}).get("Workgroup")
        )
        output_location = (
            execution_info.get("OutputLocation")
            or (execution_info.get("CalculationExecution") or {}).get("OutputLocation")
            or (execution_info.get("ResultConfiguration") or {}).get("OutputLocation")
        )

        metadata = self._build_metadata(
            context=context,
            calculation_execution_id=calculation_execution_id,
            state=state,
            reason=reason,
            submission_time=submission_time,
            completion_time=completion_time,
            workgroup=workgroup,
            output_location=output_location,
        )
        self._push_metadata_to_xcom(context=context, metadata=metadata)

        if state in AthenaHook.SPARK_FAILURE_STATES:
            self.log.error(
                "Calculation failed. CalculationExecutionId: %s, state: %s, reason: %s",
                calculation_execution_id,
                state,
                reason,
            )
            raise AirflowException(
                f"Athena Spark calculation ended in {state}. "
                f"CalculationExecutionId: {calculation_execution_id}. "
                f"Reason: {reason or 'No reason provided.'}"
            )

        if state != "COMPLETED":
            raise AirflowException(
                f"Unexpected terminal state: {state} for calculation {calculation_execution_id}. "
                "Expected COMPLETED, FAILED, or CANCELED."
            )

        self.log.info(
            "Calculation completed successfully. CalculationExecutionId: %s",
            calculation_execution_id,
        )

        return metadata

    def _build_metadata(
        self,
        *,
        context: Context,
        calculation_execution_id: str,
        state: str,
        reason: str | None,
        submission_time: Any,
        completion_time: Any,
        workgroup: str | None,
        output_location: str | None,
    ) -> dict[str, Any]:
        task_instance = context.get("ti")
        return {
            METADATA_KEY_DAG_ID: getattr(task_instance, "dag_id", None),
            METADATA_KEY_TASK_ID: getattr(task_instance, "task_id", None),
            METADATA_KEY_RUN_ID: getattr(task_instance, "run_id", None),
            METADATA_KEY_MAP_INDEX: getattr(task_instance, "map_index", -1),
            METADATA_KEY_CALCULATION_EXECUTION_ID: calculation_execution_id,
            METADATA_KEY_STATUS: state,
            METADATA_KEY_FINAL_STATE: state,
            METADATA_KEY_FAILURE_REASON: reason,
            METADATA_KEY_STATE_CHANGE_REASON: reason,
            METADATA_KEY_SUBMISSION_TIME: str(submission_time) if submission_time else None,
            METADATA_KEY_COMPLETION_TIME: str(completion_time) if completion_time else None,
            METADATA_KEY_SESSION_ID: self.session_id,
            METADATA_KEY_WORKGROUP: workgroup,
            METADATA_KEY_OUTPUT_LOCATION: output_location,
        }

    def _push_metadata_to_xcom(self, *, context: Context, metadata: dict[str, Any]) -> None:
        task_instance = context.get("ti")
        if not task_instance:
            return

        task_instance.xcom_push(
            key=METADATA_KEY_CALCULATION_EXECUTION_ID,
            value=metadata[METADATA_KEY_CALCULATION_EXECUTION_ID],
        )
        task_instance.xcom_push(key=ATHENA_SPARK_METADATA_XCOM_KEY, value=metadata)

    def on_kill(self) -> None:
        """Request cancellation of the calculation when the task is killed."""
        if self._calculation_execution_id:
            self.log.info("Received kill signal; stopping calculation %s", self._calculation_execution_id)
            try:
                self.hook.stop_calculation(self._calculation_execution_id)
            except Exception as e:
                self.log.warning(
                    "Failed to stop calculation %s: %s",
                    self._calculation_execution_id,
                    e,
                )
