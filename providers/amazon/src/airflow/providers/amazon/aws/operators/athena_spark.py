from __future__ import annotations

import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from airflow.models import BaseOperator
from airflow.providers.amazon.aws.hooks.athena import AthenaHook
from airflow.exceptions import AirflowException

if TYPE_CHECKING:
    from airflow.utils.context import Context


class AthenaSparkOperator(BaseOperator):
    """
    Submits an Apache Spark calculation to AWS Athena and waits for completion.

    :param session_id: The Athena session ID to run the calculation in. (templated)
    :param code_block: The Python or Scala code block to execute. (templated)
    :param wait_for_completion: Whether to wait for the job to finish before exiting.
    :param poll_interval: Time (in seconds) to wait between status checks.
    :param aws_conn_id: The Airflow connection used for AWS credentials.
    """

    template_fields: Sequence[str] = ("session_id", "code_block")
    ui_color = "#e27d44"

    def __init__(
        self,
        *,
        session_id: str,
        code_block: str,
        wait_for_completion: bool = True,
        poll_interval: int = 15,
        aws_conn_id: str = "aws_default",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.session_id = session_id
        self.code_block = code_block
        self.wait_for_completion = wait_for_completion
        self.poll_interval = poll_interval
        self.aws_conn_id = aws_conn_id
        self.calculation_execution_id: str | None = None

    def execute(self, context: Context) -> str:
        hook = AthenaHook(aws_conn_id=self.aws_conn_id)
        
        self.calculation_execution_id = hook.start_calculation_execution(
            session_id=self.session_id,
            code_block=self.code_block,
        )

        if not self.wait_for_completion:
            return self.calculation_execution_id

        self.log.info("Polling for calculation completion...")
        while True:
            status = hook.check_calculation_status(self.calculation_execution_id)
            self.log.info("Current calculation state is: %s", status)

            if status in hook.SPARK_TERMINAL_STATES:
                if status in hook.SPARK_FAILURE_STATES:
                    raise AirflowException(
                        f"Athena Spark job failed or was canceled. Final state: {status}"
                    )
                self.log.info("Athena Spark calculation completed successfully.")
                break
            
            time.sleep(self.poll_interval)

        # Implicitly pushed to XCom by returning the value
        return self.calculation_execution_id

    def on_kill(self) -> None:
        """Cancels the calculation if the Airflow task is killed."""
        if self.calculation_execution_id:
            self.log.info("Task killed. Canceling Athena Spark job.")
            hook = AthenaHook(aws_conn_id=self.aws_conn_id)
            hook.stop_calculation_execution(self.calculation_execution_id)