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
from workflow_restart import create_workflow_restarter


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Test PyTorch workflow restart functionality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test restarting trunk workflow for a specific commit
  python test_workflow_restart.py --workflow trunk.yml --commit abc123def --dry-run
  
  # Actually restart the workflow (be careful!)
  python test_workflow_restart.py --workflow trunk.yml --commit abc123def
  
  # List recent workflow runs
  python test_workflow_restart.py --workflow trunk.yml --list-runs
        """
    )
    
    parser.add_argument(
        "--workflow",
        required=True,
        help="Workflow file name (e.g., trunk.yml)"
    )
    
    parser.add_argument(
        "--commit",
        help="Commit SHA to restart workflow for"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without actually doing it"
    )
    
    parser.add_argument(
        "--list-runs",
        action="store_true",
        help="List recent workflow runs"
    )
    
    parser.add_argument(
        "--repo-owner",
        default="pytorch",
        help="Repository owner (default: pytorch)"
    )
    
    parser.add_argument(
        "--repo-name", 
        default="pytorch",
        help="Repository name (default: pytorch)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.verbose)
    
    # Load environment variables
    load_dotenv()
    
    try:
        # Create workflow restarter
        restarter = create_workflow_restarter()
        restarter.repo_owner = args.repo_owner
        restarter.repo_name = args.repo_name
        
        logger.info(f"Using repository: {args.repo_owner}/{args.repo_name}")
        
        if args.list_runs:
            # List recent workflow runs
            logger.info(f"Getting recent runs for workflow: {args.workflow}")
            runs = restarter.get_workflow_runs(args.workflow, limit=5)
            
            if runs:
                print(f"\\nRecent runs for {args.workflow}:")
                print("-" * 80)
                for run in runs:
                    status = run.get('status', 'unknown')
                    conclusion = run.get('conclusion', 'unknown')
                    created_at = run.get('created_at', 'unknown')
                    head_sha = run.get('head_sha', 'unknown')[:8]
                    run_number = run.get('run_number', 'unknown')
                    
                    print(f"Run #{run_number}: {status}/{conclusion} - {head_sha} - {created_at}")
            else:
                print(f"No recent runs found for {args.workflow}")
        
        elif args.commit:
            # Restart workflow for commit
            if args.dry_run:
                logger.info(f"DRY RUN: Would restart workflow {args.workflow} for commit {args.commit}")
                logger.info(f"Tag would be created: trunk/{args.commit}")
                print(f"\\n✓ DRY RUN: Ready to restart {args.workflow} for commit {args.commit}")
            else:
                logger.info(f"Restarting workflow {args.workflow} for commit {args.commit}")
                
                success = restarter.restart_workflow_for_commit(
                    workflow_name=args.workflow,
                    commit_sha=args.commit
                )
                
                if success:
                    print(f"\\n✓ Successfully restarted {args.workflow} for commit {args.commit}")
                    print(f"  Tag created: trunk/{args.commit}")
                    print(f"  Check workflow runs at: https://github.com/{args.repo_owner}/{args.repo_name}/actions")
                else:
                    print(f"\\n✗ Failed to restart {args.workflow} for commit {args.commit}")
                    return 1
        else:
            parser.error("Either --commit or --list-runs must be specified")
            
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        print(f"\\nError: {e}")
        print("Make sure GITHUB_TOKEN is set in your .env file")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\\nUnexpected error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())