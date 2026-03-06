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

from unittest import mock

import pytest

from airflow.exceptions import AirflowException
from airflow.providers.amazon.aws.hooks.athena import AthenaHook
from airflow.providers.amazon.aws.operators.athena_spark import AthenaSparkOperator


class TestAthenaSparkOperator:
    @staticmethod
    def _build_operator(**overrides):
        kwargs = {
            "task_id": "athena_spark_task",
            "session_id": "session-123",
            "code_block": "print('hello')",
            "poll_interval": 1,
            "max_poll_interval": 10,
            "max_polling_attempts": 5,
            "backoff_multiplier": 2.0,
        }
        kwargs.update(overrides)
        return AthenaSparkOperator(**kwargs)

    @staticmethod
    def _build_context():
        return {"ti": mock.MagicMock()}

    @mock.patch("airflow.providers.amazon.aws.operators.athena_spark.time.sleep")
    @mock.patch.object(AthenaHook, "check_calculation_status", side_effect=["RUNNING", "COMPLETED"])
    @mock.patch.object(AthenaHook, "start_calculation_execution", return_value="calc-1")
    def test_execute_success(self, start_calc, _check_status, mock_sleep):
        operator = self._build_operator()
        context = self._build_context()

        result = operator.execute(context)

        start_calc.assert_called_once_with(
            session_id="session-123",
            code_block="print('hello')",
            workgroup="primary",
            description=None,
            calculation_configuration=None,
            client_request_token=None,
        )
        assert result["calculation_execution_id"] == "calc-1"
        assert result["final_state"] == "COMPLETED"
        context["ti"].xcom_push.assert_any_call(key="calculation_execution_id", value="calc-1")
        context["ti"].xcom_push.assert_any_call(key="athena_spark_metadata", value=result)
        mock_sleep.assert_called_once_with(1.0)

    @pytest.mark.parametrize("terminal_state", ["FAILED", "CANCELLED"])
    @mock.patch.object(AthenaHook, "get_calculation_state_change_reason", return_value="bad state")
    @mock.patch.object(AthenaHook, "start_calculation_execution", return_value="calc-1")
    def test_execute_failure_states_raise(self, _start_calc, _reason, terminal_state):
        operator = self._build_operator()
        context = self._build_context()

        with (
            mock.patch.object(AthenaHook, "check_calculation_status", return_value=terminal_state),
            pytest.raises(AirflowException, match=f"state {terminal_state}"),
        ):
            operator.execute(context)

    @mock.patch.object(AthenaHook, "check_calculation_status", return_value=None)
    @mock.patch.object(AthenaHook, "start_calculation_execution", return_value="calc-1")
    def test_execute_malformed_state_raises(self, _start_calc, _check_status):
        operator = self._build_operator()

        with pytest.raises(AirflowException, match="Unable to determine Athena Spark calculation state"):
            operator.execute(self._build_context())

    @mock.patch("airflow.providers.amazon.aws.operators.athena_spark.time.sleep")
    @mock.patch.object(AthenaHook, "check_calculation_status", side_effect=["RUNNING", "RUNNING"])
    @mock.patch.object(AthenaHook, "start_calculation_execution", return_value="calc-1")
    def test_execute_running_until_max_attempts(self, _start_calc, _check_status, _sleep):
        operator = self._build_operator(max_polling_attempts=2)

        with pytest.raises(AirflowException, match="max_polling_attempts"):
            operator.execute(self._build_context())

    @mock.patch("airflow.providers.amazon.aws.operators.athena_spark.time.sleep")
    @mock.patch.object(AthenaHook, "check_calculation_status", side_effect=["RUNNING", "RUNNING", "COMPLETED"])
    @mock.patch.object(AthenaHook, "start_calculation_execution", return_value="calc-1")
    def test_exponential_backoff(self, _start_calc, _check_status, mock_sleep):
        operator = self._build_operator(poll_interval=1, max_poll_interval=3, backoff_multiplier=2)

        result = operator.execute(self._build_context())

        assert result["final_state"] == "COMPLETED"
        assert mock_sleep.call_args_list == [mock.call(1.0), mock.call(2.0)]

    @mock.patch.object(AthenaHook, "start_calculation_execution", return_value="calc-1")
    def test_execute_without_waiting(self, _start_calc):
        operator = self._build_operator(wait_for_completion=False)

        result = operator.execute(self._build_context())

        assert result == {
            "calculation_execution_id": "calc-1",
            "session_id": "session-123",
            "workgroup": "primary",
            "final_state": None,
            "state_change_reason": None,
        }

    @pytest.mark.parametrize(
        ("operator_kwargs", "message"),
        [
            ({"poll_interval": 0}, "poll_interval"),
            ({"poll_interval": 10, "max_poll_interval": 5}, "max_poll_interval"),
            ({"max_polling_attempts": 0}, "max_polling_attempts"),
            ({"backoff_multiplier": 0.5}, "backoff_multiplier"),
        ],
    )
    @mock.patch.object(AthenaHook, "start_calculation_execution", return_value="calc-1")
    def test_execute_invalid_polling_configuration(self, _start_calc, operator_kwargs, message):
        operator = self._build_operator(**operator_kwargs)
        with pytest.raises(AirflowException, match=message):
            operator.execute(self._build_context())
