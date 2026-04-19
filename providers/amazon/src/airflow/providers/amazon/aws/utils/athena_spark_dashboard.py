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

from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from airflow.models.taskinstance import TaskInstance
from airflow.models.xcom import XComModel
from airflow.utils.session import NEW_SESSION, provide_session

ATHENA_SPARK_METADATA_KEY = "athena_spark_metadata"

# If your operator pushes Athena Spark metadata under a different XCom key,
# update this constant to match the key used in `xcom_push(key=..., value=...)`.


def _first_metadata_value(metadata: dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty metadata value for the provided keys."""
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return None


@provide_session
def get_recent_athena_spark_runs(
    *, limit: int = 50, dag_id: str | None = None, session: Session = NEW_SESSION
) -> list[dict[str, Any]]:
    """Return recent Athena Spark runs backed by XCom metadata and task instance data."""
    ti_join = and_(
        TaskInstance.dag_id == XComModel.dag_id,
        TaskInstance.task_id == XComModel.task_id,
        TaskInstance.run_id == XComModel.run_id,
        TaskInstance.map_index == XComModel.map_index,
    )

    stmt = (
        select(XComModel, TaskInstance)
        .join(TaskInstance, ti_join)
        .where(XComModel.key == ATHENA_SPARK_METADATA_KEY)
        .order_by(XComModel.timestamp.desc())
        .limit(limit)
    )
    if dag_id:
        stmt = stmt.where(XComModel.dag_id == dag_id)

    return [_xcom_and_ti_to_row(xcom=xcom, task_instance=task_instance) for xcom, task_instance in session.execute(stmt)]


@provide_session
def get_athena_spark_run(
    *, dag_id: str, task_id: str, run_id: str, map_index: int, session: Session = NEW_SESSION
) -> dict[str, Any] | None:
    """Return one Athena Spark run by task instance identity."""
    ti_join = and_(
        TaskInstance.dag_id == XComModel.dag_id,
        TaskInstance.task_id == XComModel.task_id,
        TaskInstance.run_id == XComModel.run_id,
        TaskInstance.map_index == XComModel.map_index,
    )
    stmt = (
        select(XComModel, TaskInstance)
        .join(TaskInstance, ti_join)
        .where(
            XComModel.key == ATHENA_SPARK_METADATA_KEY,
            XComModel.dag_id == dag_id,
            XComModel.task_id == task_id,
            XComModel.run_id == run_id,
            XComModel.map_index == map_index,
        )
        .order_by(XComModel.timestamp.desc())
        .limit(1)
    )
    result = session.execute(stmt).first()
    if not result:
        return None
    xcom, task_instance = result
    return _xcom_and_ti_to_row(xcom=xcom, task_instance=task_instance)


def _xcom_and_ti_to_row(*, xcom: XComModel, task_instance: TaskInstance) -> dict[str, Any]:
    metadata = xcom.value if isinstance(xcom.value, dict) else {}
    # Adapt these fallback key lists if your Athena Spark XCom schema uses
    # different field names for timing or state values.
    started_at = _first_metadata_value(metadata, "submission_time", "start_time") or task_instance.start_date
    ended_at = _first_metadata_value(metadata, "completion_time", "end_time") or task_instance.end_date
    duration = _duration_seconds(started_at=started_at, ended_at=ended_at)

    return {
        "dag_id": _first_metadata_value(metadata, "dag_id") or xcom.dag_id,
        "task_id": _first_metadata_value(metadata, "task_id") or xcom.task_id,
        "run_id": _first_metadata_value(metadata, "run_id") or xcom.run_id,
        "map_index": xcom.map_index,
        "calculation_execution_id": _first_metadata_value(metadata, "calculation_execution_id"),
        "status": _first_metadata_value(metadata, "status", "final_state") or task_instance.state,
        "workgroup": _first_metadata_value(metadata, "workgroup"),
        "session_id": _first_metadata_value(metadata, "session_id"),
        "failure_reason": _first_metadata_value(metadata, "failure_reason", "state_change_reason"),
        "state_change_reason": _first_metadata_value(metadata, "state_change_reason", "failure_reason"),
        "xcom_timestamp": xcom.timestamp,
        "submission_time": started_at,
        "completion_time": ended_at,
        "start_time": started_at,
        "end_time": ended_at,
        "duration_seconds": duration,
        "metadata": metadata,
    }


def _duration_seconds(*, started_at: datetime | None, ended_at: datetime | None) -> float | None:
    if not started_at or not ended_at:
        return None
    return (ended_at - started_at).total_seconds()
