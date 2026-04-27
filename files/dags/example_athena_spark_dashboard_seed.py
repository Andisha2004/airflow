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

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator


def push_metadata(**context):
    context["ti"].xcom_push(
        key="athena_spark_metadata",
        value={
            "calculation_execution_id": "demo-calc-001",
            "final_state": "COMPLETED",
            "workgroup": "demo-workgroup",
            "session_id": "demo-session-001",
            "state_change_reason": "",
        },
    )


with DAG(
    dag_id="example_athena_spark_dashboard_seed",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
):
    PythonOperator(
        task_id="seed_athena_spark_metadata",
        python_callable=push_metadata,
    )
