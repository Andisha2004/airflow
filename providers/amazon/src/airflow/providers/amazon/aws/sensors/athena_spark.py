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
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from airflow.exceptions import AirflowException
from airflow.providers.amazon.aws.hooks.athena import AthenaHook
from airflow.sensors.base import BaseSensorOperator

if TYPE_CHECKING:
    from airflow.utils.context import Context


ATHENA_SPARK_METADATA_XCOM_KEY = "athena_spark_metadata"


class AthenaSparkSensor(BaseSensorOperator):
    """
    Polls the status of an AWS Athena Spark calculation until it reaches a terminal state.

    :param calculation_execution_id: The ID of the calculation to monitor. (templated)
    :param aws_conn_id: The Airflow connection used for AWS credentials.
    """

    template_fields: Sequence[str] = ("calculation_execution_id",)
    ui_color = "#44e2b5"

    def __init__(
        self,
        *,
        calculation_execution_id: str,
        aws_conn_id: str = "aws_default",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.calculation_execution_id = calculation_execution_id
        self.aws_conn_id = aws_conn_id

    def poke(self, context: Context) -> bool:
        """Checks the current status of the Spark calculation."""
        hook = AthenaHook(aws_conn_id=self.aws_conn_id)
        state = hook.check_calculation_status(self.calculation_execution_id)

        self.log.info("Calculation %s state is: %s", self.calculation_execution_id, state)

        if state in hook.SPARK_FAILURE_STATES:
            self._push_sensor_metadata(context=context, hook=hook, state=state)
            raise AirflowException(
                f"Calculation {self.calculation_execution_id} failed with state: {state}"
            )

        if state == "COMPLETED":
            self._push_sensor_metadata(context=context, hook=hook, state=state)

        # Return True to stop the sensor if it succeeds, False to wait and poll again
        return state == "COMPLETED"

    def _push_sensor_metadata(self, *, context: Context, hook: AthenaHook, state: str | None) -> None:
        task_instance = context.get("ti")
        if not task_instance:
            return

        reason = hook.get_calculation_state_change_reason(self.calculation_execution_id)
        execution_info = hook.get_calculation_info(self.calculation_execution_id)
        status = (
            execution_info.get("Status")
            or (execution_info.get("CalculationExecution") or {}).get("Status")
            or {}
        )
        metadata = {
            "dag_id": getattr(task_instance, "dag_id", None),
            "task_id": getattr(task_instance, "task_id", None),
            "run_id": getattr(task_instance, "run_id", None),
            "map_index": getattr(task_instance, "map_index", -1),
            "calculation_execution_id": self.calculation_execution_id,
            "status": state,
            "final_state": state,
            "failure_reason": reason,
            "state_change_reason": reason,
            "submission_time": str(status.get("SubmissionDateTime")) if status.get("SubmissionDateTime") else None,
            "completion_time": str(status.get("CompletionDateTime")) if status.get("CompletionDateTime") else None,
            "workgroup": (
                execution_info.get("WorkGroup")
                or (execution_info.get("CalculationExecution") or {}).get("WorkGroup")
            ),
            "output_location": (
                execution_info.get("OutputLocation")
                or (execution_info.get("CalculationExecution") or {}).get("OutputLocation")
            ),
        }
        task_instance.xcom_push(key=ATHENA_SPARK_METADATA_XCOM_KEY, value=metadata)
