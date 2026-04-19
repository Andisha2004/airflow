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
from pathlib import Path
from urllib.parse import quote, urlparse

from airflow.configuration import conf
from airflow.providers.amazon.aws.utils.athena_spark_dashboard import (
    get_athena_spark_run,
    get_recent_athena_spark_runs,
)
from airflow.providers.common.compat.sdk import AirflowPlugin

try:
    from fastapi import FastAPI, Query, Request
    from fastapi.responses import HTMLResponse
    from fastapi.templating import Jinja2Templates
except ImportError:
    FastAPI = None
    Jinja2Templates = None


TEMPLATES = (
    Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
    if Jinja2Templates is not None
    else None
)


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


def _build_detail_rows(row: dict) -> list[tuple[str, object]]:
    return [
        ("DAG ID", row["dag_id"]),
        ("Task ID", row["task_id"]),
        ("Run ID", row["run_id"]),
        ("Map Index", row["map_index"]),
        ("CalculationExecutionId", row.get("calculation_execution_id") or "-"),
        ("Status", row.get("status") or "-"),
        ("Workgroup", row.get("workgroup") or "-"),
        ("Session ID", row.get("session_id") or "-"),
        ("Failure Reason", row.get("failure_reason") or row.get("state_change_reason") or "-"),
        ("Submission Time", row.get("submission_time") or row.get("start_time") or "-"),
        ("Completion Time", row.get("completion_time") or row.get("end_time") or "-"),
        ("Duration(s)", row.get("duration_seconds") or "-"),
        ("Output Location", row.get("metadata", {}).get("output_location") or "-"),
    ]


def _create_dashboard_app() -> FastAPI | None:
    if FastAPI is None or TEMPLATES is None:
        return None

    app = FastAPI()

    def _render_runs_page(request: Request, dag_id: str | None = None):
        rows = get_recent_athena_spark_runs(limit=100, dag_id=dag_id)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="athena_spark_dashboard/runs_list.html",
            context={
                "dag_id_filter": dag_id or "",
                "rows": rows,
                "build_task_run_url": _build_task_run_url,
                "quote": quote,
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, dag_id: str | None = Query(default=None)):
        return _render_runs_page(request, dag_id)

    @app.get("/runs", response_class=HTMLResponse)
    def list_runs(request: Request, dag_id: str | None = Query(default=None)):
        return _render_runs_page(request, dag_id)

    @app.get("/detail", response_class=HTMLResponse)
    def detail(
        request: Request,
        dag_id: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        run_id: str | None = Query(default=None),
        map_index: int = Query(default=-1),
    ):
        if not dag_id or not task_id or not run_id:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="athena_spark_dashboard/run_details.html",
                context={
                    "error": "Missing dag_id/task_id/run_id query parameters.",
                    "detail_rows": [],
                    "metadata_json": "",
                    "task_run_url": None,
                },
            )

        row = get_athena_spark_run(dag_id=dag_id, task_id=task_id, run_id=run_id, map_index=map_index)
        if not row:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="athena_spark_dashboard/run_details.html",
                context={
                    "error": "No Athena Spark run metadata found for this task instance.",
                    "detail_rows": [],
                    "metadata_json": "",
                    "task_run_url": None,
                },
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="athena_spark_dashboard/run_details.html",
            context={
                "error": None,
                "detail_rows": _build_detail_rows(row),
                "metadata_json": json.dumps(row.get("metadata") or {}, indent=2, sort_keys=True, default=str),
                "task_run_url": _build_task_run_url(row),
            },
        )

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
