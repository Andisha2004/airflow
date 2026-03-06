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
from html import escape
from urllib.parse import quote, urlparse

from airflow.configuration import conf
from airflow.providers.amazon.aws.utils.athena_spark_dashboard import (
    get_athena_spark_run,
    get_recent_athena_spark_runs,
)
from airflow.providers.common.compat.sdk import AirflowPlugin

try:
    from fastapi import FastAPI, Query
    from fastapi.responses import HTMLResponse
except ImportError:
    FastAPI = None


def _get_base_url_path(path: str) -> str:
    """Construct URL path with API base_url prefix."""
    base_url = conf.get("api", "base_url", fallback="/")
    if base_url.startswith(("http://", "https://")):
        base_path = urlparse(base_url).path
    else:
        base_path = base_url

    base_path = base_path.rstrip("/")
    return f"{base_path}{path}"


def _build_task_run_url(row: dict) -> str:
    dag_id = quote(str(row["dag_id"]))
    run_id = quote(str(row["run_id"]))
    task_id = quote(str(row["task_id"]))
    map_index = row["map_index"]
    return _get_base_url_path(f"/dags/{dag_id}/runs/{run_id}/tasks/{task_id}?map_index={map_index}")


def _build_list_html(*, rows: list[dict], dag_id_filter: str) -> str:
    rows_html: list[str] = []
    for row in rows:
        detail_link = (
            "./detail?dag_id="
            f"{quote(str(row['dag_id']))}&task_id={quote(str(row['task_id']))}"
            f"&run_id={quote(str(row['run_id']))}&map_index={row['map_index']}"
        )
        rows_html.append(
            "<tr>"
            f"<td>{escape(str(row['dag_id']))}</td>"
            f"<td>{escape(str(row['task_id']))}</td>"
            f"<td>{escape(str(row['run_id']))}</td>"
            f"<td>{row['map_index']}</td>"
            f"<td><code>{escape(str(row.get('calculation_execution_id') or '-'))}</code></td>"
            f"<td>{escape(str(row.get('status') or '-'))}</td>"
            f"<td>{escape(str(row.get('workgroup') or '-'))}</td>"
            f"<td>{escape(str(row.get('start_time') or '-'))}</td>"
            f"<td>{escape(str(row.get('end_time') or '-'))}</td>"
            f"<td>{escape(str(row.get('duration_seconds') or '-'))}</td>"
            f"<td><a href='{detail_link}'>Details</a> | <a href='{_build_task_run_url(row)}'>Task Run</a></td>"
            "</tr>"
        )

    table = (
        "<p>No Athena Spark runs found.</p>"
        if not rows_html
        else (
            "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-size:13px;'>"
            "<tr><th>DAG ID</th><th>Task ID</th><th>Run ID</th><th>Map</th><th>CalculationExecutionId</th>"
            "<th>Status</th><th>Workgroup</th><th>Start</th><th>End</th><th>Duration(s)</th><th>Actions</th></tr>"
            f"{''.join(rows_html)}"
            "</table>"
        )
    )

    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Athena Spark Dashboard</title></head><body>"
        "<h2>Athena Spark Dashboard</h2>"
        "<form method='get' style='margin-bottom:12px;'>"
        "<label><strong>DAG ID filter:</strong></label> "
        f"<input name='dag_id' value='{escape(dag_id_filter)}' placeholder='example_dag' /> "
        "<button type='submit'>Apply</button> <a href='?'>Clear</a>"
        "</form>"
        f"{table}"
        "</body></html>"
    )


def _build_detail_html(*, row: dict | None, error: str | None) -> str:
    if error:
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>Athena Spark Run Details</title></head><body>"
            "<h3>Athena Spark Run Details</h3>"
            f"<p>{escape(error)}</p>"
            "<p><a href='./'>Back to dashboard</a></p>"
            "</body></html>"
        )

    if row is None:
        return _build_detail_html(row=None, error="No Athena Spark run metadata found for this task instance.")
    values = [
        ("DAG ID", row["dag_id"]),
        ("Task ID", row["task_id"]),
        ("Run ID", row["run_id"]),
        ("Map Index", row["map_index"]),
        ("CalculationExecutionId", row.get("calculation_execution_id") or "-"),
        ("Status", row.get("status") or "-"),
        ("Workgroup", row.get("workgroup") or "-"),
        ("Session ID", row.get("session_id") or "-"),
        ("State Change Reason", row.get("state_change_reason") or "-"),
        ("Start", row.get("start_time") or "-"),
        ("End", row.get("end_time") or "-"),
        ("Duration(s)", row.get("duration_seconds") or "-"),
    ]
    table_rows = "".join(
        f"<tr><th align='left'>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>" for key, value in values
    )

    metadata_json = json.dumps(row.get("metadata") or {}, indent=2, sort_keys=True, default=str)
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Athena Spark Run Details</title></head><body>"
        "<h2>Athena Spark Run Details</h2>"
        "<p><a href='./'>Back to dashboard</a></p>"
        "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;'>"
        f"{table_rows}"
        "</table>"
        f"<p><a href='{_build_task_run_url(row)}'>Open task run</a></p>"
        "<h4>Raw Metadata</h4>"
        f"<pre>{escape(metadata_json)}</pre>"
        "</body></html>"
    )


def _create_dashboard_app() -> FastAPI | None:
    if FastAPI is None:
        return None

    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def list_runs(dag_id: str | None = Query(default=None)):
        rows = get_recent_athena_spark_runs(limit=100, dag_id=dag_id)
        return HTMLResponse(_build_list_html(rows=rows, dag_id_filter=dag_id or ""))

    @app.get("/detail", response_class=HTMLResponse)
    def detail(
        dag_id: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        run_id: str | None = Query(default=None),
        map_index: int = Query(default=-1),
    ):
        if not dag_id or not task_id or not run_id:
            return HTMLResponse(_build_detail_html(row=None, error="Missing dag_id/task_id/run_id query parameters."))

        row = get_athena_spark_run(dag_id=dag_id, task_id=task_id, run_id=run_id, map_index=map_index)
        if not row:
            return HTMLResponse(
                _build_detail_html(row=None, error="No Athena Spark run metadata found for this task instance.")
            )
        return HTMLResponse(_build_detail_html(row=row, error=None))

    return app


dashboard_app = _create_dashboard_app()


class AthenaSparkDashboardPlugin(AirflowPlugin):
    name = "athena_spark_dashboard_plugin"

    if dashboard_app is not None:
        fastapi_apps = [
            {
                "app": dashboard_app,
                "url_prefix": "/athena_spark_dashboard",
                "name": "Athena Spark Dashboard",
            }
        ]
        external_views = [
            {
                "name": "Athena Spark",
                "href": _get_base_url_path("/athena_spark_dashboard/"),
                "destination": "nav",
                "category": "browse",
                "url_route": "athena_spark_dashboard",
            }
        ]
