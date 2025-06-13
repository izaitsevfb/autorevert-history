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

## Configuration

Configure the following environment variables in your `.env` file:
- PyTorch HUD endpoints
- ClickHouse connection details
- Authentication tokens