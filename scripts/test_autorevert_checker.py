#!/usr/bin/env python3
"""
CLI tool for autorevert pattern detection with automatic revert checking.
"""

import argparse
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from autorevert_checker import create_clickhouse_client, AutorevertPatternChecker


def main():
    """CLI interface for autorevert pattern detection."""
    parser = argparse.ArgumentParser(
        description="Detect autorevert patterns in PyTorch CI workflows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s pull --hours 48
  %(prog)s inductor --hours 72 --verbose
  %(prog)s "linux-binary-manywheel" --hours 24 -v
        """
    )
    
    parser.add_argument(
        'workflow',
        help='Workflow name to analyze (e.g., "pull", "inductor")'
    )
    parser.add_argument(
        '--hours',
        type=int,
        default=48,
        help='Lookback window in hours (default: 48)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output including commit summaries'
    )
    parser.add_argument(
        '--test-connection',
        action='store_true',
        help='Test ClickHouse connection and exit'
    )
    
    args = parser.parse_args()
    
    # Test connection if requested
    if args.test_connection:
        try:
            client = create_clickhouse_client()
            client.query('SELECT 1')
            print("✓ ClickHouse connection successful")
            return 0
        except Exception as e:
            print(f"✗ ClickHouse connection failed: {e}")
            return 1
    
    try:
        # Initialize checker
        client = create_clickhouse_client()
        checker = AutorevertPatternChecker(client, workflow_name=args.workflow, lookback_hours=args.hours)
        
        # Fetch data
        if args.verbose:
            print(f"Fetching commits for workflow '{args.workflow}' (last {args.hours}h)...")
        
        commits = checker.workflow_commits
        
        if not commits:
            print(f"No commit data found for workflow '{args.workflow}' in last {args.hours}h")
            return 1
        
        if args.verbose:
            print(f"Found {len(commits)} commits with job data")
            print("\nRecent commits:")
            for i, commit in enumerate(commits[:10]):
                failed_count = len(commit.failed_jobs)
                total_count = len(commit.jobs)
                pending = " (PENDING)" if commit.has_pending_jobs else ""
                print(f"  {i+1:2d}. {commit.head_sha[:8]} ({commit.created_at.strftime('%m-%d %H:%M')}) - "
                      f"{failed_count:2d}/{total_count:2d} failed{pending}")
        
        # Detect patterns
        patterns = checker.detect_autorevert_pattern()
        
        if patterns:
            print(f"✓ {len(patterns)} AUTOREVERT PATTERN{'S' if len(patterns) > 1 else ''} DETECTED")
            
            # Create a revert checker (with extended lookback for finding reverts)
            revert_checker = AutorevertPatternChecker(
                client, 
                workflow_name=None, 
                lookback_hours=args.hours * 2
            )
            
            # Track reverts
            reverted_patterns = []
            
            for i, pattern in enumerate(patterns, 1):
                if len(patterns) > 1:
                    print(f"\nPattern #{i}:")
                
                print(f"Failure rule: '{pattern['failure_rule']}'")
                print(f"Recent commits with failure: {' '.join(sha[:8] for sha in pattern['newer_commits'])}")
                print(f"Older commit without failure: {pattern['older_commit'][:8]}")
                
                # Check if the second commit (older of the two failures) was reverted
                second_commit = pattern['newer_commits'][1]
                revert_result = revert_checker.is_commit_reverted(second_commit)
                
                if revert_result:
                    print(f"✓ REVERTED: {second_commit[:8]} was reverted by {revert_result['revert_sha'][:8]} "
                          f"after {revert_result['hours_after_target']:.1f} hours")
                    reverted_patterns.append(pattern)
                else:
                    print(f"✗ NOT REVERTED: {second_commit[:8]} was not reverted")
                
                if args.verbose:
                    print(f"Failed jobs ({len(pattern['failed_job_names'])}):")
                    for job in pattern['failed_job_names'][:5]:
                        print(f"  - {job}")
                    if len(pattern['failed_job_names']) > 5:
                        print(f"  ... and {len(pattern['failed_job_names']) - 5} more")
                    
                    print(f"Job coverage overlap ({len(pattern['older_job_coverage'])}):")
                    for job in pattern['older_job_coverage'][:3]:
                        print(f"  - {job}")
                    if len(pattern['older_job_coverage']) > 3:
                        print(f"  ... and {len(pattern['older_job_coverage']) - 3} more")
                    
                    if revert_result and args.verbose:
                        print(f"Revert message: {revert_result['revert_message'][:100]}...")
            
            # Print summary statistics
            print("\n" + "="*50)
            print("SUMMARY STATISTICS")
            print("="*50)
            print(f"Workflow: {args.workflow}")
            print(f"Timeframe: {args.hours} hours")
            print(f"Commits checked: {len(commits)}")
            print(f"Patterns detected: {len(patterns)}")
            print(f"Actual reverts: {len(reverted_patterns)} ({len(reverted_patterns)/len(patterns)*100:.1f}%)")
            
            if reverted_patterns:
                print(f"\nReverted patterns:")
                for pattern in reverted_patterns:
                    print(f"  - {pattern['failure_rule']}: {pattern['newer_commits'][1][:8]}")
            
            return 0
        else:
            print("✗ No autorevert patterns detected")
            
            if args.verbose and len(commits) >= 3:
                print(f"\nDiagnostic (first 3 commits):")
                for i, commit in enumerate(commits[:3]):
                    failures = {j.classification_rule for j in commit.failed_jobs if j.classification_rule}
                    print(f"  {i+1}. {commit.head_sha[:8]}: {len(failures)} unique failure types")
                    if failures:
                        for rule in list(failures)[:2]:
                            print(f"     - {rule}")
                        if len(failures) > 2:
                            print(f"     ... and {len(failures) - 2} more")
            
            return 1
            
    except Exception as e:
        print(f"✗ Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())