#!/usr/bin/env python3
"""
CLI script to test the workflow restart functionality.
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
from workflow_restart import dispatch_workflow


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Test PyTorch workflow restart")
    
    parser.add_argument("--workflow", required=True, help="Workflow file name (e.g., trunk.yml)")
    parser.add_argument("--commit", required=True, help="Commit SHA to restart workflow for")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without doing it")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Load environment variables
    load_dotenv()
    
    try:
        if args.dry_run:
            print(f"DRY RUN: Would dispatch workflow {args.workflow} for commit {args.commit}")
            print(f"Tag: trunk/{args.commit}")
            return 0
        
        success = dispatch_workflow(args.workflow, args.commit)
        
        if success:
            print(f"✓ Successfully dispatched {args.workflow} for commit {args.commit}")
            return 0
        else:
            print(f"✗ Failed to dispatch {args.workflow} for commit {args.commit}")
            return 1
            
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())