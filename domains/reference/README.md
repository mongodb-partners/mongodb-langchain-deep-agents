# Reference pack

Industry-neutral baseline. Use this pack for demos and integration tests
when you do not need domain-specific flavor. The knowledge base talks
about MongoDB Atlas features (Vector Search, Hybrid Search, Knowledge
Graph); the operational schema is a generic e-commerce sketch.

## Personas

- Solutions architect evaluating deep-agent + MongoDB
- Developer onboarding to the codebase
- CI running the integration tier

## Operational schema

| Collection | Shape |
|---|---|
| `customers` | `{ _id, name, email, tier, region, joined_at }` |
| `orders` | `{ _id, customer_id, total, status, items: [...] }` |
| `products` | `{ _id, name, price, category, in_stock }` |

## Knowledge-base themes

- MongoDB Atlas Vector Search overview
- Hybrid search (BM25 + vector)
- Knowledge-graph entity/relation modelling
- Deep-agent architecture concepts

## Demo flow

```mermaid
flowchart TD
    U["Solutions architect / developer<br/>'What is Atlas Vector Search?'<br/>'Show me a MongoDBSaver example.'"]
    U --> P["Main planner<br/>(deepagents + write_todos)"]
    P -->|generic MongoDB Q| KB[("knowledge_base<br/>Atlas $vectorSearch<br/>+ $search hybrid")]
    P -->|entity/relation Q| KG[("knowledge_graph<br/>MongoDBGraphStore")]
    P -->|'list 2 sample orders'| DA["Data agent<br/>(safety-wrapped NL to MQL)"]
    P -->|deep dive| R["Researcher subagent<br/>task(question)"]
    R --> KB
    R --> W["web_search<br/>(Tavily)"]
    W --> FC["fetch_and_cache<br/>(enriches KB)"]
    FC --> KB
    DA --> OC[("customers / orders / products<br/>allow_list from pack.yaml")]
    P --> VFS[("VFS<br/>(GridFS or S3)<br/>per thread_id")]
    P --> ANS["Cited answer<br/>+ optional artifact"]

    classDef mongo fill:#00684a,color:#fff,stroke:#004c3a
    classDef tool fill:#f0f4ff,stroke:#3b5bdb
    class KB,KG,OC,VFS mongo
    class DA,R,W,FC tool
```

Probing questions the reference demo answers:
- "How does Atlas Vector Search differ from Atlas Search?"
- "Show me two recent orders and which customer placed them."
- "Which LangChain MongoDB package owns the checkpoint collections?"

## Swap recipe

See [docs/domain-packs.md](../../docs/domain-packs.md) for the full
authoring guide.
