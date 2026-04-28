# Documentation

Reference documentation for `mongodb-langchain-deep-agents`.

## Start here

- **[Getting Started](getting-started.md)** - install, configure, and run your first research turn
- **[Architecture](architecture.md)** - planning agent, researcher subagent, VFS, plans persistence

## Reference

- **[API Reference](api-reference.md)** - HTTP endpoints, CLI commands, Python factories, tools
- **[Configuration](configuration.md)** - every environment variable, collection, and index name

## How-to guides

- **[Deploy](DEPLOY.md)** - one-command Docker + Kanopy via `scripts/deploy.sh`
- **[Developer Guide](developer-guide.md)** - local development loop: lint, type-check, test
- **[Testing](testing.md)** - unit vs. integration tests
- **[Functional Testing](functional-testing.md)** - reproducible end-to-end runbook against live Atlas
- **[Deployment](deployment.md)** - Dockerfile, docker-compose, LangGraph Platform (lower-level)
- **[Streaming](streaming.md)** - Kafka → Atlas Stream Processing → change-stream ingestion
- **[Evals](evals.md)** - starter LangSmith dataset + uploader + custom evaluators
- **[Domain Adaptation](domain-adaptation.md)** - swap `domain/` to retarget the reference

## Explanation

- **[Security Model](security.md)** - TLS enforcement, safety wrapper, memory + VFS scoping, RBAC
- **[VFS Backends](vfs-backends.md)** - GridFS vs S3, IAM policy, contract tests
- **[MongoDB Backend](mongodb-backend.md)** - how deepagents' filesystem tools route through MongoDB

## Operator runbooks

- **[operators/atlas-cli-setup.md](operators/atlas-cli-setup.md)** - one-shot cluster + index provisioning
- **[operators/rbac-example.md](operators/rbac-example.md)** - least-privilege Atlas roles
