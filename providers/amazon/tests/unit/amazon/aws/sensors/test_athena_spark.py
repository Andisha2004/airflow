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

from types import SimpleNamespace
from unittest import mock

import pytest

from airflow.exceptions import AirflowException
from airflow.providers.amazon.aws.hooks.athena import AthenaHook
from airflow.providers.amazon.aws.sensors.athena_spark import (
    ATHENA_SPARK_METADATA_XCOM_KEY,
    AthenaSparkSensor,
)

CALC_ID = "calc-exec-123"


@pytest.fixture
def sensor() -> AthenaSparkSensor:
    return AthenaSparkSensor(task_id="test_athena_spark_sensor", calculation_execution_id=CALC_ID)


@pytest.fixture
def task_instance() -> SimpleNamespace:
    return SimpleNamespace(
        dag_id="example_dag",
        task_id="test_athena_spark_sensor",
        run_id="manual__2026-04-28T00:00:00+00:00",
        map_index=2,
        xcom_push=mock.Mock(),
    )


class TestAthenaSparkSensor:
    def test_init(self, sensor: AthenaSparkSensor):
        assert sensor.calculation_execution_id == CALC_ID
        assert sensor.aws_conn_id == "aws_default"

    def test_template_fields(self):
        assert AthenaSparkSensor.template_fields == ("calculation_execution_id",)

    @mock.patch.object(AthenaHook, "get_calculation_info")
    @mock.patch.object(AthenaHook, "get_calculation_state_change_reason", return_value=None)
    @mock.patch.object(AthenaHook, "check_calculation_status", return_value="COMPLETED")
    def test_poke_completed_pushes_metadata(
        self,
        mock_check: mock.Mock,
        mock_reason: mock.Mock,
        mock_info: mock.Mock,
        sensor: AthenaSparkSensor,
        task_instance: SimpleNamespace,
    ):
        mock_info.return_value = {
            "Status": {
                "SubmissionDateTime": "2026-04-28T00:00:01+00:00",
                "CompletionDateTime": "2026-04-28T00:00:05+00:00",
            },
            "WorkGroup": "primary",
            "OutputLocation": "s3://bucket/output/",
        }

        result = sensor.poke({"ti": task_instance})

        assert result is True
        task_instance.xcom_push.assert_called_once()
        key = task_instance.xcom_push.call_args.kwargs["key"]
        value = task_instance.xcom_push.call_args.kwargs["value"]
        assert key == ATHENA_SPARK_METADATA_XCOM_KEY
        assert value["dag_id"] == "example_dag"
        assert value["task_id"] == "test_athena_spark_sensor"
        assert value["run_id"] == "manual__2026-04-28T00:00:00+00:00"
        assert value["map_index"] == 2
        assert value["calculation_execution_id"] == CALC_ID
        assert value["status"] == "COMPLETED"
        assert value["final_state"] == "COMPLETED"
        assert value["failure_reason"] is None
        assert value["submission_time"] == "2026-04-28T00:00:01+00:00"
        assert value["completion_time"] == "2026-04-28T00:00:05+00:00"
        assert value["workgroup"] == "primary"
        assert value["output_location"] == "s3://bucket/output/"
        mock_check.assert_called_once_with(CALC_ID)
        mock_reason.assert_called_once_with(CALC_ID)
        mock_info.assert_called_once_with(CALC_ID)

    @mock.patch.object(AthenaHook, "get_calculation_info")
    @mock.patch.object(AthenaHook, "get_calculation_state_change_reason", return_value="Spark failed")
    @mock.patch.object(AthenaHook, "check_calculation_status", return_value="FAILED")
    def test_poke_failed_raises_and_pushes_metadata(
        self,
        mock_check: mock.Mock,
        mock_reason: mock.Mock,
        mock_info: mock.Mock,
        sensor: AthenaSparkSensor,
        task_instance: SimpleNamespace,
    ):
        mock_info.return_value = {
            "CalculationExecution": {
                "Status": {
                    "SubmissionDateTime": "2026-04-28T00:00:01+00:00",
                    "CompletionDateTime": "2026-04-28T00:00:03+00:00",
                },
                "WorkGroup": "fallback-group",
                "OutputLocation": "s3://bucket/failure/",
            }
        }

        with pytest.raises(AirflowException, match="failed with state: FAILED"):
            sensor.poke({"ti": task_instance})

        task_instance.xcom_push.assert_called_once()
        value = task_instance.xcom_push.call_args.kwargs["value"]
        assert value["status"] == "FAILED"
        assert value["failure_reason"] == "Spark failed"
        assert value["state_change_reason"] == "Spark failed"
        assert value["workgroup"] == "fallback-group"
        assert value["output_location"] == "s3://bucket/failure/"
        mock_check.assert_called_once_with(CALC_ID)
        mock_reason.assert_called_once_with(CALC_ID)
        mock_info.assert_called_once_with(CALC_ID)

    @mock.patch.object(AthenaHook, "get_calculation_info")
    @mock.patch.object(AthenaHook, "get_calculation_state_change_reason")
    @mock.patch.object(AthenaHook, "check_calculation_status", return_value="RUNNING")
    def test_poke_running_returns_false_without_metadata(
        self,
        mock_check: mock.Mock,
        mock_reason: mock.Mock,
        mock_info: mock.Mock,
        sensor: AthenaSparkSensor,
        task_instance: SimpleNamespace,
    ):
        result = sensor.poke({"ti": task_instance})

        assert result is False
        task_instance.xcom_push.assert_not_called()
        mock_check.assert_called_once_with(CALC_ID)
        mock_reason.assert_not_called()
        mock_info.assert_not_called()

    @mock.patch.object(AthenaHook, "get_calculation_info", return_value={})
    @mock.patch.object(AthenaHook, "get_calculation_state_change_reason", return_value=None)
    def test_push_sensor_metadata_no_task_instance(
        self,
        mock_reason: mock.Mock,
        mock_info: mock.Mock,
        sensor: AthenaSparkSensor,
    ):
        sensor._push_sensor_metadata(context={}, hook=mock.create_autospec(AthenaHook, instance=True), state=None)

        mock_reason.assert_not_called()
        mock_info.assert_not_called()
