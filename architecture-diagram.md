# Reusable Architecture Pattern for New Projects

This is the general design pattern to reuse for new integrations or platform projects. It follows the same structure as the COIC-style architecture but uses generic names so it can be applied to other products.

```mermaid
flowchart LR
    classDef source fill:#f3f4f6,stroke:#374151,stroke-width:1.5px,color:#111827
    classDef api fill:#dbeafe,stroke:#1d4ed8,stroke-width:1.5px,color:#0f172a
    classDef process fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px,color:#0f172a
    classDef queue fill:#fef3c7,stroke:#d97706,stroke-width:1.5px,color:#111827
    classDef app fill:#f3e8ff,stroke:#7c3aed,stroke-width:1.5px,color:#111827
    classDef target fill:#e0f2fe,stroke:#0284c7,stroke-width:1.5px,color:#0f172a
    classDef shared fill:#e5e7eb,stroke:#374151,stroke-width:1.5px,color:#111827

    subgraph SOURCE[Source Systems]
        S1[Partner / Vendor / CRM / ERP]
        S2[Sales / Channel / Internal System]
        S3[Regional / Business Unit System]
    end
    class S1,S2,S3 source

    subgraph EDGE[Experience Layer]
        A1[Experience API]
        A2[Experience API]
        A3[Experience API]
    end
    class A1,A2,A3 api

    subgraph CORE[Process / System Layer]
        P1[Process API]
        P2[System API]
        P3[Transformation / Orchestration]
    end
    class P1,P2,P3 process

    subgraph MSG[Integration Layer]
        Q1[Queue / Topic / Event Bus]
        Q2[PubSub / SNS / SQS / Kafka]
        Q3[Async Processing Channel]
    end
    class Q1,Q2,Q3 queue

    subgraph APP[Consumer / Worker Apps]
        W1[Consumer App]
        W2[Batch App]
        W3[Event Worker]
    end
    class W1,W2,W3 app

    subgraph TARGET[Target Systems]
        T1[CRM / ERP / Salesforce / Portal]
        T2[Downstream Partner System]
        T3[(Database / Cache / Metadata Store)]
    end
    class T1,T2,T3 target

    subgraph SHARED[Shared Platform Services]
        C1[Common Library]
        C2[Auth / Security Layer]
        C3[Config / Secrets / Observability]
    end
    class C1,C2,C3 shared

    S1 --> A1
    S2 --> A2
    S3 --> A3

    A1 --> P1
    A2 --> P2
    A3 --> P3

    P1 --> Q1
    P2 --> Q2
    P3 --> Q3

    Q1 --> W1
    Q2 --> W2
    Q3 --> W3

    W1 --> T1
    W2 --> T2
    W3 --> T3

    A1 -. shared utilities .-> C1
    A2 -. shared utilities .-> C1
    P1 -. shared utilities .-> C1
    P2 -. shared utilities .-> C1
    W1 -. auth + config .-> C2
    W2 -. auth + config .-> C2
    W3 -. observability + secrets .-> C3
```

## Design pattern summary

This architecture follows a repeatable pattern for integration-heavy platforms:

1. Source systems push or pull data.
2. Experience APIs receive external requests.
3. Process and system APIs transform and orchestrate the work.
4. Queues or event buses decouple synchronous and asynchronous processing.
5. Consumer or worker apps complete business operations.
6. Downstream systems are updated with the final results.
7. Shared platform functions handle auth, secrets, logging, and common business utilities.

## When to use this pattern

Use this pattern when your project includes any of the following:

- external API integrations
- system-to-system data exchange
- event-driven processing
- asynchronous worker flows
- multi-step business operations
- shared security and platform services

## Project template to copy

For a new project, create these groups:

- Source systems
- Experience layer
- Process/system layer
- Integration / event layer
- Consumer / worker apps
- Target systems
- Shared common library
- Security and platform services

This gives a clean and scalable foundation for most enterprise integration projects.
