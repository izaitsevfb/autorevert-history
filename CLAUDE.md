# PyTorch Autorevert System

## Project Overview
System to automatically restart failed PyTorch CI workflows and track their success/failure for intelligent autorevert decisions.

## Architecture
```
autorevert-history/
├── src/
│   ├── autorevert_checker.py   # Pattern detection & multi-workflow support
│   ├── workflow_restart.py     # GitHub workflow dispatch API
│   └── workflow_checker.py     # ClickHouse job differentiation
├── scripts/
│   ├── test_autorevert_checker.py  # CLI for pattern detection
│   ├── test_workflow_restart.py    # Workflow restart testing
│   └── test_multi_workflow.py      # Multi-workflow demo
└── docs/
    └── workflow-job-differentiation.md # Research findings
```

## Key Components

### Autorevert Pattern Detection (`autorevert_checker.py`)
- **Pattern**: 2 recent commits with same failure + 1 older without = autorevert candidate
- **Multi-workflow support**: Batch fetching with per-workflow caching
- **Deduplication**: Same commits across workflows tracked with `additional_workflows`
- **Revert detection**: Checks if commits were reverted via commit message patterns

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
- **Autorevert pattern detection** with revert checking
- **Multi-workflow support** with intelligent deduplication
- **CLI tools** for pattern detection and analysis

### 🔄 Recent Improvements
- **Multi-workflow CLI**: Support comma/space separated workflows
- **Batch queries**: Single ClickHouse query for all workflows
- **Pattern deduplication**: Track same commits across workflows
- **Revert detection**: Automatic checking if pattern commits were reverted

### 📊 Usage Examples
```bash
# Single workflow
python scripts/test_autorevert_checker.py pull --hours 48

# Multiple workflows (comma-separated)
python scripts/test_autorevert_checker.py pull,trunk,inductor --hours 48

# Multiple workflows (space-separated)
python scripts/test_autorevert_checker.py "pull trunk" --hours 72 --verbose

# API usage
from autorevert_checker import create_clickhouse_client, AutorevertPatternChecker

client = create_clickhouse_client()
checker = AutorevertPatternChecker(
    client, 
    workflow_names=['pull', 'trunk', 'inductor'],
    lookback_hours=48
)
patterns = checker.detect_autorevert_pattern()  # Deduplicated results
```

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
- Integration with autorevert decision engine
- Automated workflow restart based on pattern detection
- Track success rate of restarted workflows