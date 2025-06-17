# PyTorch Autorevert

A collection of scripts to manage PyTorch workflow autoreverts and restart failed workflows.

## Setup

1. Activate your virtual environment:
   ```bash
   source venv/bin/activate  # or your venv activation command
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy and configure environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your actual values
   ```

## Usage

### Restart Failed Workflows
```bash
python scripts/restart_workflows.py
```

### Find potential revert patterns:
```
python src/autorevert_checker.py pull --hours 168
python src/autorevert_checker.py inductor --hours 72 --verbose
```
