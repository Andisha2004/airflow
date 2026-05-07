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

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Mapping

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from airflow.models.taskinstance import TaskInstance
from airflow.models.xcom import XComModel
from airflow.utils.session import NEW_SESSION, provide_session

ATHENA_SPARK_XCOM_KEY = "athena_spark_metadata"
# Backward-compatible alias. Update the constant above if the operator/sensor
# use a different XCom key in the future.
ATHENA_SPARK_METADATA_KEY = ATHENA_SPARK_XCOM_KEY

# If your operator pushes Athena Spark metadata under a different XCom key,
# update this constant to match the key used in `xcom_push(key=..., value=...)`.
#
# If you later want to filter to only a subset of Athena Spark tasks, the safest
# place to add that logic is in `get_recent_athena_spark_runs()` by adding more
# conditions to the SQLAlchemy statement, for example on `XComModel.task_id`.
#
# The normalization logic below is intentionally defensive. If your operator
# changes payload shape, update the fallback key lists in
# `_normalize_athena_spark_run_record()` instead of spreading schema handling
# into the view layer.


def _first_metadata_value(metadata: dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty metadata value for the provided keys."""
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return None


def _coerce_metadata_mapping(value: Any) -> dict[str, Any]:
    """
    Convert the raw XCom value into a dictionary for downstream normalization.

    Some operators push a Python dict directly. Others may push a JSON string.
    Any unsupported payload shape falls back to an empty dict so the UI can
    render a graceful empty state instead of crashing.
    """
    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}

    if isinstance(value, Mapping):
        return dict(value)

    return {}


def normalize_xcom_payload(
    xcom_record: XComModel,
    task_instance: TaskInstance | None = None,
) -> dict[str, Any]:
    """
    Normalize one Athena Spark XCom record into a stable UI-friendly dictionary.

    This is the main schema adapter for the dashboard. If the operator or sensor
    changes the exact payload fields later, update the fallback key handling here
    instead of changing the templates or route code.
    """
    if task_instance is None:
        task_instance = SimpleNamespace(
            dag_id=xcom_record.dag_id,
            task_id=xcom_record.task_id,
            run_id=xcom_record.run_id,
            map_index=xcom_record.map_index,
            state=None,
            start_date=None,
            end_date=None,
        )
    metadata = _coerce_metadata_mapping(xcom_record.value)
    return _normalize_athena_spark_run_record(
        xcom=xcom_record,
        task_instance=task_instance,
        metadata=metadata,
    )


def _latest_athena_spark_xcom_subquery(*, dag_id_filter: str | None = None):
    stmt = (
        select(
            XComModel.dag_id.label("dag_id"),
            XComModel.task_id.label("task_id"),
            XComModel.run_id.label("run_id"),
            XComModel.map_index.label("map_index"),
            func.max(XComModel.timestamp).label("latest_timestamp"),
        )
        .where(XComModel.key == ATHENA_SPARK_XCOM_KEY)
        .group_by(
            XComModel.dag_id,
            XComModel.task_id,
            XComModel.run_id,
            XComModel.map_index,
        )
    )
    if dag_id_filter:
        stmt = stmt.where(XComModel.dag_id == dag_id_filter)
    return stmt.subquery()


@provide_session
def get_recent_athena_spark_runs(
    *,
    limit: int = 50,
    dag_id_filter: str | None = None,
    status_filter: str | None = None,
    session: Session = NEW_SESSION,
) -> list[dict[str, Any]]:
    """Return recent Athena Spark runs backed by XCom metadata and task instance data."""
    latest_xcom = _latest_athena_spark_xcom_subquery(dag_id_filter=dag_id_filter)
    ti_join = and_(
        TaskInstance.dag_id == XComModel.dag_id,
        TaskInstance.task_id == XComModel.task_id,
        TaskInstance.run_id == XComModel.run_id,
        TaskInstance.map_index == XComModel.map_index,
    )

    stmt = (
        select(XComModel, TaskInstance)
        .join(
            latest_xcom,
            and_(
                XComModel.dag_id == latest_xcom.c.dag_id,
                XComModel.task_id == latest_xcom.c.task_id,
                XComModel.run_id == latest_xcom.c.run_id,
                XComModel.map_index == latest_xcom.c.map_index,
                XComModel.timestamp == latest_xcom.c.latest_timestamp,
            ),
        )
        .join(TaskInstance, ti_join)
        .order_by(XComModel.timestamp.desc())
        .limit(limit)
    )

    rows = [normalize_xcom_payload(xcom, task_instance) for xcom, task_instance in session.execute(stmt)]
    return _filter_runs_by_status(rows, status_filter=status_filter)


@provide_session
def get_athena_spark_run_detail(
    *, dag_id: str, task_id: str, run_id: str, map_index: int, session: Session = NEW_SESSION
) -> dict[str, Any] | None:
    """Return one Athena Spark run by task instance identity."""
    latest_xcom = _latest_athena_spark_xcom_subquery(dag_id_filter=dag_id)
    ti_join = and_(
        TaskInstance.dag_id == XComModel.dag_id,
        TaskInstance.task_id == XComModel.task_id,
        TaskInstance.run_id == XComModel.run_id,
        TaskInstance.map_index == XComModel.map_index,
    )
    stmt = (
        select(XComModel, TaskInstance)
        .join(
            latest_xcom,
            and_(
                XComModel.dag_id == latest_xcom.c.dag_id,
                XComModel.task_id == latest_xcom.c.task_id,
                XComModel.run_id == latest_xcom.c.run_id,
                XComModel.map_index == latest_xcom.c.map_index,
                XComModel.timestamp == latest_xcom.c.latest_timestamp,
            ),
        )
        .join(TaskInstance, ti_join)
        .where(
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
    return normalize_xcom_payload(xcom, task_instance)


def get_athena_spark_run(
    *, dag_id: str, task_id: str, run_id: str, map_index: int, session: Session = NEW_SESSION
) -> dict[str, Any] | None:
    """
    Backward-compatible alias for older route code.

    New code should call `get_athena_spark_run_detail()`.
    """
    return get_athena_spark_run_detail(
        dag_id=dag_id,
        task_id=task_id,
        run_id=run_id,
        map_index=map_index,
        session=session,
    )


def compute_dashboard_summary(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = {
        "ALL": len(runs),
        "FAILED": 0,
        "QUEUED": 0,
        "RUNNING": 0,
        "SUCCESS": 0,
        "REQUIRED_ACTION": 0,
    }
    for row in runs:
        status = str(row.get("status") or "UNKNOWN").upper()
        if status in counts and status != "ALL":
            counts[status] += 1

    return [
        {
            "key": "ALL",
            "label": "All",
            "count": counts["ALL"],
            "tone": "all",
            "icon": "●",
        },
        {
            "key": "FAILED",
            "label": "Failed",
            "count": counts["FAILED"],
            "tone": "failed",
            "icon": "✕",
        },
        {
            "key": "QUEUED",
            "label": "Queued",
            "count": counts["QUEUED"],
            "tone": "queued",
            "icon": "◌",
        },
        {
            "key": "RUNNING",
            "label": "Running",
            "count": counts["RUNNING"],
            "tone": "running",
            "icon": "↻",
        },
        {
            "key": "SUCCESS",
            "label": "Success",
            "count": counts["SUCCESS"],
            "tone": "success",
            "icon": "✓",
        },
        {
            "key": "REQUIRED_ACTION",
            "label": "Required Actions",
            "count": counts["REQUIRED_ACTION"],
            "tone": "required-action",
            "icon": "!",
        },
    ]


def _normalize_athena_spark_run_record(
    *, xcom: XComModel, task_instance: TaskInstance, metadata: dict[str, Any]
) -> dict[str, Any]:
    """
    Normalize one Athena Spark XCom payload into a stable UI-facing structure.

    Stable keys used by the UI:
    - dag_id
    - task_id
    - run_id
    - calculation_execution_id
    - status
    - submission_time
    - completion_time
    - failure_reason
    - output_location

    Extra keys such as map_index, session_id, workgroup, duration_seconds and
    raw metadata are also returned because the details page benefits from them.
    """
    # Adapt these fallback key lists if your Athena Spark XCom schema uses
    # different field names for timing or state values.
    started_at = _first_metadata_value(metadata, "submission_time", "start_time") or task_instance.start_date
    ended_at = _first_metadata_value(metadata, "completion_time", "end_time") or task_instance.end_date
    duration = _duration_seconds(started_at=started_at, ended_at=ended_at)
    output_location = _first_metadata_value(metadata, "output_location", "result_output_location", "s3_output")
    normalized_status = _normalize_status(
        _first_metadata_value(metadata, "status", "state", "final_state") or task_instance.state
    )

    return {
        "dag_id": _first_metadata_value(metadata, "dag_id") or xcom.dag_id,
        "task_id": _first_metadata_value(metadata, "task_id") or xcom.task_id,
        "run_id": _first_metadata_value(metadata, "run_id") or xcom.run_id,
        "map_index": xcom.map_index,
        "calculation_execution_id": _first_metadata_value(metadata, "calculation_execution_id"),
        "status": normalized_status,
        "workgroup": _first_metadata_value(metadata, "workgroup"),
        "session_id": _first_metadata_value(metadata, "session_id"),
        "failure_reason": _first_metadata_value(metadata, "failure_reason", "state_change_reason"),
        "state_change_reason": _first_metadata_value(metadata, "state_change_reason", "failure_reason"),
        "output_location": output_location,
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


def _normalize_status(status: Any) -> str:
    raw_status = str(status or "UNKNOWN").upper()
    if raw_status in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
        return "SUCCESS"
    if raw_status in {"FAILED", "FAILURE", "CANCELED", "CANCELLED"}:
        return "FAILED"
    if raw_status in {"RUNNING", "STARTING", "CREATING", "CREATED"}:
        return "RUNNING"
    if raw_status in {"QUEUED", "PENDING"}:
        return "QUEUED"
    if raw_status == "REQUIRED_ACTION":
        return "REQUIRED_ACTION"
    return raw_status


def _filter_runs_by_status(
    runs: list[dict[str, Any]],
    *,
    status_filter: str | None,
) -> list[dict[str, Any]]:
    normalized_filter = _normalize_status(status_filter)
    if not normalized_filter or normalized_filter == "ALL" or normalized_filter == "UNKNOWN":
        return runs
    return [row for row in runs if str(row.get("status") or "UNKNOWN").upper() == normalized_filter]
