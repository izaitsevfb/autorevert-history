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

# Multi-workflow analysis
python scripts/test_multi_workflow.py
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
