# Project Report #1: AthenaSparkOperator for Apache Airflow

### 1. Summary of Project Progress
Since the project plan, our team successfully initialized our local development environments and mapped the architectural flow of the Apache Airflow Amazon Provider. We finalized our UI requirements, deciding to build a read-only Spark Job Monitor dashboard using Airflow's Plugin Manager to view XCom metadata, ensuring we do not clutter the core database. For Sprint 1, we successfully drafted the core `AthenaHook` methods and their associated unit tests, establishing the foundation for our operator.

---

### 2. Development Methodology: Iterative Refinement
We are utilizing an **Iterative Refinement** methodology combined with Agile sprint planning. We began with a formal requirements gathering phase to lock down the scope of the AWS Athena API. In Sprint 1, we implemented the first iteration of the backend (the Hook). In upcoming sprints, we will iterate upward to the Operator, Sensor, and finally the UI dashboard, testing and refining the data contract at each layer.

---

### 3. Architecture Diagrams

#### Component Diagram
*Caption: The flow of data from the Airflow UI/Scheduler, through our new AthenaSparkOperator, down to the modified AthenaHook, which uses the boto3 library to communicate with the AWS Athena Spark API.*

```
flowchart LR
    classDef node fill:none,stroke:#333,stroke-width:1px;
    
    subgraph core_env [Airflow Core]
        style core_env fill:#f4f6f8,stroke:#cdd4da,stroke-width:1px
        UI[Airflow UI / Scheduler]
        DAG[User DAG]
        XCom[(Airflow XCom)]
    end

    subgraph provider_env [Amazon Provider Package]
        style provider_env fill:#E1EDF2,stroke:#dee2e6,stroke-width:1px
        Operator[AthenaSparkOperator]
        Hook[AthenaHook]
        Plugin[Spark Job Monitor UI Plugin]
    end

    subgraph aws_env [AWS Cloud]
        style aws_env fill:#fff8e1,stroke:#ffe082,stroke-width:1px
        Boto[boto3 AWS SDK]
        Athena[AWS Athena Spark API]
        S3[(Amazon S3 Storage)]
    end

    UI --> DAG
    DAG -->|Submits params| Operator
    Operator -->|Calls| Hook
    Hook -->|Authenticates & Requests| Boto
    Boto -->|REST API| Athena
    Athena -->|Writes output| S3
    Plugin -.->|Reads metadata| XCom
    Operator -.->|Saves metadata| XCom
    
    class UI,DAG,XCom,Operator,Hook,Plugin,Boto,Athena,S3 node

```

Deployment Diagram
```
flowchart TB
    classDef node fill:none,stroke:#333,stroke-width:1px;

    subgraph local_env [Local Dev Environment]
        style local_env fill:#e3f2fd,stroke:#90caf9,stroke-width:1px
        Docker[Docker Desktop]
        Breeze[Airflow Breeze Engine]
        Docker --- Breeze
    end

    subgraph cicd_env [CI/CD Pipeline]
        style cicd_env fill:#f5f5f5,stroke:#e0e0e0,stroke-width:1px
        Pytest[Pytest Test Suite]
        Moto[moto: Mock AWS API]
        Pytest -->|Mocks responses| Moto
    end

    subgraph aws_prod [AWS Cloud Production]
        style aws_prod fill:#fff3e0,stroke:#ffb74d,stroke-width:1px
        Engine[Athena Serverless Engine]
        S3[(Amazon S3)]
        Engine -->|Output & Logs| S3
    end

    Breeze -.->|Unit Testing| Pytest
    Breeze ==>|Acceptance Testing| Engine
    
    class Docker,Breeze,Pytest,Moto,Engine,S3 node
```