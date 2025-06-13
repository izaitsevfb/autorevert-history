# Workflow Job Differentiation in PyTorch HUD and ClickHouse

## Key Identification Fields

### Primary Method: `head_branch` Field
- **Restarted workflows**: `head_branch = "trunk/{commit_sha}"`
- **Original workflows**: `head_branch = "main"`

### Alternative Methods
- **Event type**: `event = "workflow_dispatch"` (restarted) vs `"push"` (original)
- **Workflow run ID**: `run_id` uniquely identifies each workflow attempt
- **Referenced workflows**: `referenced_workflows[].ref = "refs/tags/trunk/{commit_sha}"`

## Recommended Queries

### Most Precise: Filter by Dispatch Reference
```sql
SELECT * FROM workflow_job 
WHERE head_sha = '{commit_sha}'
  AND head_branch = 'trunk/{commit_sha}'
```

### Alternative: Filter by Event Type
```sql
SELECT wj.* FROM workflow_job wj
JOIN workflow_run wr ON wj.run_id = wr.id
WHERE wr.head_sha = '{commit_sha}'
  AND wr.event = 'workflow_dispatch'
ORDER BY wr.created_at DESC
```

## Test Case Results
**Commit**: `2d3615f577894c7a117a55e85bb8371bb598ec50`
- Original workflow: `run_id = 15595052847`, `head_branch = "main"`
- Restarted workflow: `run_id = 15644112883`, `head_branch = "trunk/2d3615f577894c7a117a55e85bb8371bb598ec50"`

## Implementation
Use `head_branch` field for 100% precision in identifying restarted workflow jobs.