# PyTorch Autorevert

Scripts to detect autorevert patterns and restart failed workflows.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # Add your credentials
```

## Usage

### Detect Autorevert Patterns
```bash
# Single workflow
python scripts/test_autorevert_checker.py pull --hours 48

# Multiple workflows
python scripts/test_autorevert_checker.py pull,trunk,inductor --hours 48

# With verbose output
python scripts/test_autorevert_checker.py pull --hours 48 --verbose
```

### Debug Specific Commits
```bash
# Analyze why a commit was/wasn't detected as a pattern
python scripts/debug_commit.py f179b719 pull

# Multiple workflows
python scripts/debug_commit.py c79c7bbe pull,trunk,inductor

# Custom window size
python scripts/debug_commit.py 18e42406 pull --window 12

# Show all failures in surrounding commits
python scripts/debug_commit.py d83636de pull --show-all-failures
```

### API Usage
```python
from autorevert_checker import create_clickhouse_client, AutorevertPatternChecker

client = create_clickhouse_client()
checker = AutorevertPatternChecker(
    client, 
    workflow_names=['pull', 'trunk', 'inductor'],
    lookback_hours=48
)

# Get patterns with automatic deduplication
patterns = checker.detect_autorevert_pattern()
```
