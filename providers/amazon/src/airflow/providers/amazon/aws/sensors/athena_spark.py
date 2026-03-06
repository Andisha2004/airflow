from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from airflow.sensors.base import BaseSensorOperator
from airflow.providers.amazon.aws.hooks.athena import AthenaHook
from airflow.exceptions import AirflowException

if TYPE_CHECKING:
    from airflow.utils.context import Context


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
            raise AirflowException(
                f"Calculation {self.calculation_execution_id} failed with state: {state}"
            )

        # Return True to stop the sensor if it succeeds, False to wait and poll again
        return state == "COMPLETED"