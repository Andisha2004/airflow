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

from datetime import datetime, timedelta
from types import SimpleNamespace

from airflow.providers.amazon.aws.utils.athena_spark_dashboard import (
    _duration_seconds,
    _first_metadata_value,
    _xcom_and_ti_to_row,
)


def test_duration_seconds_with_none_inputs():
    assert _duration_seconds(started_at=None, ended_at=None) is None


def test_duration_seconds_with_datetimes():
    started = datetime(2026, 3, 6, 10, 0, 0)
    ended = started + timedelta(seconds=42)
    assert _duration_seconds(started_at=started, ended_at=ended) == 42.0


def test_xcom_and_ti_to_row_maps_expected_fields():
    xcom = SimpleNamespace(
        dag_id="example_dag",
        task_id="athena_spark_task",
        run_id="manual__2026-03-06T10:00:00+00:00",
        map_index=-1,
        value={
            "calculation_execution_id": "calc-123",
            "final_state": "COMPLETED",
            "workgroup": "primary",
            "session_id": "session-1",
            "state_change_reason": None,
        },
        timestamp=datetime(2026, 3, 6, 10, 0, 10),
    )
    task_instance = SimpleNamespace(
        state="success",
        start_date=datetime(2026, 3, 6, 10, 0, 0),
        end_date=datetime(2026, 3, 6, 10, 0, 30),
    )

    row = _xcom_and_ti_to_row(xcom=xcom, task_instance=task_instance)

    assert row["dag_id"] == "example_dag"
    assert row["task_id"] == "athena_spark_task"
    assert row["run_id"].startswith("manual__")
    assert row["calculation_execution_id"] == "calc-123"
    assert row["status"] == "COMPLETED"
    assert row["workgroup"] == "primary"
    assert row["duration_seconds"] == 30.0


def test_xcom_and_ti_to_row_falls_back_to_ti_state_for_missing_metadata_state():
    xcom = SimpleNamespace(
        dag_id="example_dag",
        task_id="athena_spark_task",
        run_id="run-1",
        map_index=0,
        value={},
        timestamp=datetime(2026, 3, 6, 10, 0, 10),
    )
    task_instance = SimpleNamespace(state="failed", start_date=None, end_date=None)

    row = _xcom_and_ti_to_row(xcom=xcom, task_instance=task_instance)

    assert row["status"] == "failed"
    assert row["duration_seconds"] is None


def test_first_metadata_value_returns_first_present_key():
    metadata = {
        "final_state": "COMPLETED",
        "submission_time": "2026-03-06T10:00:00+00:00",
    }

    assert _first_metadata_value(metadata, "status", "final_state") == "COMPLETED"
    assert _first_metadata_value(metadata, "start_time", "submission_time") == "2026-03-06T10:00:00+00:00"
    assert _first_metadata_value(metadata, "missing_key") is None


def test_xcom_and_ti_to_row_supports_requested_xcom_field_names():
    xcom = SimpleNamespace(
        dag_id="fallback_dag",
        task_id="fallback_task",
        run_id="fallback_run",
        map_index=-1,
        value={
            "dag_id": "metadata_dag",
            "task_id": "metadata_task",
            "run_id": "metadata_run",
            "calculation_execution_id": "calc-456",
            "status": "FAILED",
            "submission_time": datetime(2026, 3, 6, 10, 0, 0),
            "completion_time": datetime(2026, 3, 6, 10, 5, 0),
            "failure_reason": "Spark driver failed",
            "output_location": "s3://example-bucket/output/",
        },
        timestamp=datetime(2026, 3, 6, 10, 5, 10),
    )
    task_instance = SimpleNamespace(
        state="success",
        start_date=datetime(2026, 3, 6, 9, 59, 0),
        end_date=datetime(2026, 3, 6, 10, 6, 0),
    )

    row = _xcom_and_ti_to_row(xcom=xcom, task_instance=task_instance)

    assert row["dag_id"] == "metadata_dag"
    assert row["task_id"] == "metadata_task"
    assert row["run_id"] == "metadata_run"
    assert row["status"] == "FAILED"
    assert row["submission_time"] == datetime(2026, 3, 6, 10, 0, 0)
    assert row["completion_time"] == datetime(2026, 3, 6, 10, 5, 0)
    assert row["failure_reason"] == "Spark driver failed"
    assert row["metadata"]["output_location"] == "s3://example-bucket/output/"
    assert row["duration_seconds"] == 300.0
