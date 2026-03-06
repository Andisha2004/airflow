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

from airflow.providers.amazon.aws.plugins.athena_spark_dashboard import AthenaSparkDashboardPlugin
from airflow.providers.common.compat.sdk import AirflowPlugin


def test_plugin_is_airflow_plugin():
    plugin = AthenaSparkDashboardPlugin()
    assert isinstance(plugin, AirflowPlugin)


def test_plugin_name():
    plugin = AthenaSparkDashboardPlugin()
    assert plugin.name == "athena_spark_dashboard_plugin"


def test_plugin_exposes_airflow3_ui_extension_points():
    plugin = AthenaSparkDashboardPlugin()
    assert getattr(plugin, "appbuilder_views", []) == []
    assert len(getattr(plugin, "fastapi_apps", [])) == 1
    assert len(getattr(plugin, "external_views", [])) == 1
