from datetime import datetime
from airflow import DAG
from airflow.providers.amazon.aws.operators.athena_spark import AthenaSparkOperator

# PySpark script that creates a small dataframe and prints it.
HELLO_WORLD_SPARK_CODE = """
print("--- STARTING AIRFLOW SPARK DEMO ---")
data = [("Alice", 34), ("Bob", 45), ("Charlie", 28)]
columns = ["Name", "Age"]

df = spark.createDataFrame(data, columns)
df.show()
print("--- DEMO COMPLETE ---")
"""

# TODO: Replace this with the Session ID from the AWS Console
#Athena -> Workgroups -> Notebooks
DEMO_SESSION_ID = "c4ce6fd6-9c38-1908-ed3c-1cc172dfccd4"

with DAG(
    dag_id="athena_spark_hello_world",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    tags=["aws", "athena", "spark", "demo"],
) as dag:

    # Using the Operator we built in Sprint 1 & 2
    run_spark_job = AthenaSparkOperator(
        task_id="submit_hello_world_calculation",
        session_id=DEMO_SESSION_ID,
        code_block=HELLO_WORLD_SPARK_CODE,
        wait_for_completion=True,
        poll_interval=10,
        region_name="us-east-2",
    )

    run_spark_job