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
from airflow.providers.amazon.aws.sensors.athena_spark import AthenaSparkSensor


@pytest.fixture
def sensor():
    return AthenaSparkSensor(
        task_id="test_athena_spark_sensor",
        calculation_execution_id="calc-123",
        aws_conn_id="aws_default",
    )


class TestAthenaSparkSensor:
    def test_init(self, sensor):
        assert sensor.calculation_execution_id == "calc-123"
        assert sensor.aws_conn_id == "aws_default"

    def test_template_fields(self):
        assert AthenaSparkSensor.template_fields == ("calculation_execution_id",)

    @mock.patch.object(AthenaHook, "check_calculation_status", return_value="COMPLETED")
    def test_poke_returns_true_on_completed(self, mock_check, sensor):
        assert sensor.poke({}) is True
        mock_check.assert_called_once_with("calc-123")

    @mock.patch.object(AthenaHook, "check_calculation_status", return_value="RUNNING")
    def test_poke_returns_false_on_running(self, mock_check, sensor):
        assert sensor.poke({}) is False
        mock_check.assert_called_once_with("calc-123")

    @pytest.mark.parametrize("state", ["FAILED", "CANCELED"])
    @mock.patch.object(AthenaHook, "check_calculation_status")
    def test_poke_raises_on_failure_states(self, mock_check, state, sensor):
        mock_check.return_value = state
        with pytest.raises(AirflowException, match="failed with state"):
            sensor.poke({})

