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

import importlib.util
from pathlib import Path
from unittest.mock import Mock

from airflow.models.dagbag import DagBag


ROOT_DIR = Path(__file__).resolve().parents[4]
DAG_FILE = ROOT_DIR / "files" / "dags" / "seed_athena_spark_xcom.py"


def _load_seed_dag_module():
    spec = importlib.util.spec_from_file_location("seed_athena_spark_xcom_module", DAG_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_athena_spark_dag_loads_and_has_expected_structure():
    dagbag = DagBag(dag_folder=str(DAG_FILE), include_examples=False)

    assert str(DAG_FILE) not in dagbag.import_errors

    dag = dagbag.get_dag("seed_athena_spark_xcom")
    assert dag is not None
    assert dag.schedule_interval is None

    expected_tasks = {"seed_completed", "seed_failed", "seed_malformed"}
    assert set(dag.task_ids) == expected_tasks

    assert dag.get_task("seed_completed").downstream_task_ids == {"seed_failed"}
    assert dag.get_task("seed_failed").downstream_task_ids == {"seed_malformed"}
    assert dag.get_task("seed_malformed").downstream_task_ids == set()


def test_push_athena_spark_metadata_pushes_expected_xcom_key():
    module = _load_seed_dag_module()
    mock_ti = Mock(spec=["xcom_push"])
    payload = {"calculation_execution_id": "calc-123", "final_state": "COMPLETED"}

    module.get_current_context = Mock(return_value={"ti": mock_ti})
    module._push_athena_spark_metadata(payload)

    mock_ti.xcom_push.assert_called_once_with(key="athena_spark_metadata", value=payload)
