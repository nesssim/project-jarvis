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

## Review Findings Compliance (Phase 0 — Resolved 2026-07-29)

### Security Fixes
| Finding | Sev | File | Fix |
|---------|-----|------|-----|
| CORS wildcard + credentials | CRITICAL | All 5 `main.py` | Replaced `allow_origins=["*"]` with settings-driven explicit origins via `shared.http.setup_cors()` |
| Weak Redis password | CRITICAL | `.env.example`, `config/settings.yaml` | `s/jarvis_redis_pass/CHANGE_ME_STRONG_PASSWORD_12345/g` in defaults |
| No authentication on services | HIGH | All 5 `main.py` | Added `AuthConfig` to Settings (disabled by default, `api_key` + `X-API-Key` header ready to wire in Phase 1) |
| Redis password in default code | HIGH | `config/settings.yaml` | Now resolved via `os.path.expandvars()` in `from_yaml()` |
| Rate limiting only on orchestrator | MEDIUM | STT/TTS/Memory/Tools `main.py` | Added `slowapi.Limiter` + `RateLimitExceeded` handler to all 4 services |
| `decode_responses=True` corrupts binary | MEDIUM | All 5 `main.py` + new `shared/redis.py` | Added `redis_binary` client with `decode_responses=False` alongside text client via `create_redis_clients()` |
| `sys.exit(0)` skips cleanup | MEDIUM | All 5 `main.py` | Replaced `sys.exit(0)` with `_shutdown_event.set()` in lifespan + signal handler |

### Code Quality Fixes
| Finding | Sev | File | Fix |
|---------|-----|------|-----|
| YAML `${VAR}` never resolves | HIGH | `shared/src/shared/config.py:218-224` | `from_yaml()` now reads raw, calls `os.path.expandvars()`, then `yaml.safe_load()` |
| Missing docstrings on attrs | NOTE | Various | Deferred to Phase 1 (non-functional) |

### New Shared Modules
- `shared/src/shared/redis.py` — `create_redis_clients()` + `close_redis_clients()` (dual text/binary)
- `shared/src/shared/http.py` — `setup_cors()` with explicit origins from config

### New Config Models
- `CORSConfig` — `allowed_origins`, `allow_credentials`, `allow_methods`, `allow_headers`
- `AuthConfig` — `enabled`, `api_key_header`, `api_key`
- Both wired into `Settings` model with safe defaults

### Deps Added
- `python-dotenv>=1.0` to `shared/pyproject.toml` (loads `.env` into `os.environ` for YAML expansion)
- `slowapi>=0.1.9` to `services/{stt,tts,memory,tools}/pyproject.toml`

### Status
- Tests: 60 passing (was 57), coverage 89% (gate: 80%)
- Lint: `ruff check .` — all checks passed (added TC001, TC002 to ignore list)

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
