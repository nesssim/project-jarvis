# JARVIS Workflow Rules

## Pre-Task Workflow

Before starting ANY new task or project:

1. **Load matching skills first** — Identify 2-3 skills from available_skills that match the task requirements and load them via the `skill` tool. Never exceed 4 skills to respect context limits.

2. **Call `planner` agent if the task is fundemental and new and contains more than 3 diffrent steps to accomplish ** — Have the planner create a full implementation plan with phases, dependencies, and parallelization strategy.

3. **Parallel agent execution** — Deploy multiple independent coding agents simultaneously for speed, ensuring each has clear scope boundaries.

4. **Code review** — After code is written, use `code-reviewer` agent to review all deliverables.

5. **Security review** — Use `security-reviewer` for authentication, input handling, API endpoints, and sensitive data.

6. **Verify** — Run lint/typecheck/tests before marking complete.

## Skill Selection Heuristic
- Python projects: `python-patterns`, `coding-standards`
- Docker/infra: `docker-patterns`, `kubernetes-patterns`
- Backend/API: `backend-patterns`, `api-design`
- Frontend/React: `react-patterns`, `frontend-patterns`, `motion-foundations`
- Database: `postgres-patterns`, `database-migrations`
- Testing: `tdd-workflow`, `python-testing`, `e2e-testing`
- ML: `mle-workflow`, `pytorch-patterns`

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
