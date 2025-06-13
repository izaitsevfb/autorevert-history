# PyTorch Autorevert System

## Project Overview
System to automatically restart failed PyTorch CI workflows and track their success/failure for intelligent autorevert decisions.

## Architecture
```
autorevert-history/
├── src/
│   ├── workflow_restart.py     # GitHub workflow dispatch API
│   └── workflow_checker.py     # ClickHouse job differentiation
├── scripts/
│   └── test_workflow_restart.py # CLI testing
└── docs/
    └── workflow-job-differentiation.md # Research findings
```

## Key Components

### Workflow Restart (`workflow_restart.py`)
- Uses GitHub API `workflow_dispatch` to restart failed workflows
- Creates new workflow runs with `trunk/{commit_sha}` tag references
- Maintains workflow run tracking for success evaluation

### Job Differentiation (`workflow_checker.py`)
- **Problem**: Distinguish old vs new jobs after workflow restart
- **Solution**: Use `head_branch` field in ClickHouse `workflow_job` table
- **Precision**: 100% accurate identification via dispatch reference

## Critical Discovery: Workflow Job Differentiation

### ClickHouse Schema Insights
- **Original workflows**: `head_branch = "main"`, `event = "push"`
- **Restarted workflows**: `head_branch = "trunk/{commit_sha}"`, `event = "workflow_dispatch"`

### Optimized Query (Materialized View + Existence Check)
```sql
SELECT 1 as count
FROM workflow_job FINAL
WHERE (id, run_id) IN (
  SELECT DISTINCT id, run_id
  FROM materialized_views.workflow_job_by_head_sha
  WHERE head_sha = {commit_sha:String}
)
  AND workflow_event = {workflow_event:String}
  AND head_branch = {head_branch:String}
  AND workflow_name = {workflow_name:String}
LIMIT 1
```

### Performance
- **Materialized view optimization** for fast head_sha lookups
- **Existence check** (`SELECT 1` + `LIMIT 1`) instead of counting
- **Eliminated expensive JOINs** between `workflow_job` and `workflow_run`
- **Precise filtering** via `head_branch = "trunk/{commit_sha}"`

## Implementation Status

### ✅ Completed
- Workflow restart mechanism via GitHub API
- ClickHouse job differentiation research
- Query optimization (removed JOINs)
- Client migration: `clickhouse-driver` → `clickhouse-connect==0.8.14`

### 🔄 Test Case
- **Commit**: `2d3615f577894c7a117a55e85bb8371bb598ec50`
- **Original**: run_id `15595052847`, failed, `head_branch="main"`
- **Restarted**: run_id `15644112883`, in-progress, `head_branch="trunk/2d3615f..."`

## Environment Variables
```bash
CLICKHOUSE_HOST=
CLICKHOUSE_PORT=
CLICKHOUSE_USER=
CLICKHOUSE_PASSWORD=
GITHUB_TOKEN=
```

## Dependencies
- `clickhouse-connect==0.8.14` (HTTP protocol support)
- `requests>=2.31.0` (GitHub API)
- `python-dotenv>=1.0.0` (env management)

## Next Phase
Integration with autorevert decision engine using precise job filtering for workflow restart evaluation.