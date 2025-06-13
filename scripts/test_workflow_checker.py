#!/usr/bin/env python3
"""
CLI script to test the workflow restart checker functionality.
"""

import sys
import argparse
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from workflow_checker import WorkflowRestartChecker


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Test workflow restart checker")
    
    parser.add_argument("--workflow", required=True, help="Workflow file name (e.g., trunk.yml)")
    parser.add_argument("--commit", help="Check specific commit SHA")
    parser.add_argument("--days", type=int, default=7, help="Days back for bulk query (default: 7)")

    # parse --dry-run flag
    parser.add_argument(
        "--dry-run", action="store_true", help="Perform a dry run without making changes"
    )
    
    args = parser.parse_args()

    try:
        checker = WorkflowRestartChecker()

        # dry run mode
        if args.dry_run:
            print("Dry run mode enabled. No changes will be made.")
            if not checker.connection_test():
                print("ClickHouse connection test failed. Exiting.")
                return 1
            print("ClickHouse connection test passed. Ready to check workflows.")
            return 0


        if args.commit:
            # Check specific commit
            result = checker.has_restarted_workflow(args.workflow, args.commit)
            print(f"Commit {args.commit}: {'✓ RESTARTED' if result else '✗ Not restarted'}")
        else:
            # Get all restarted commits in date range
            commits = checker.get_restarted_commits(args.workflow, args.days)
            print(f"Restarted commits for {args.workflow} (last {args.days} days):")
            if commits:
                for commit in sorted(commits):
                    print(f"  ✓ {commit}")
            else:
                print("  No restarted workflows found")
                
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())