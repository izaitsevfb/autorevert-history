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
python scripts/test_autorevert_checker.py pull --hours 48
python scripts/test_autorevert_checker.py inductor --hours 72 --verbose
```

### Restart Failed Workflows
```bash
python scripts/restart_workflows.py
```
