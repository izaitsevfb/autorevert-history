#!/usr/bin/env python3
"""
CLI tool for optimistic autorevert pattern detection with automatic revert checking.

Detects failures that appear on a commit but weren't present in the 8 hours before
and persist in commits within 8 hours after.
"""

import argparse
import os
import re
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from autorevert_checker import create_clickhouse_client, AutorevertPatternChecker


def main():
    """CLI interface for autorevert pattern detection."""
    parser = argparse.ArgumentParser(
        description="Detect optimistic autorevert patterns in PyTorch CI workflows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s pull --hours 48
  %(prog)s inductor --hours 72 --verbose
  %(prog)s "linux-binary-manywheel" --hours 24 -v
  %(prog)s pull,trunk,inductor --hours 48
  %(prog)s "pull trunk" --hours 72 --verbose
        """
    )
    
    parser.add_argument(
        'workflows',
        help='Workflow name(s) to analyze - single name or comma/space separated list (e.g., "pull" or "pull,trunk,inductor")'
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
    
    # Parse workflow names (support both comma and space separation)
    workflow_names = []
    if ',' in args.workflows:
        workflow_names = [w.strip() for w in args.workflows.split(',')]
    else:
        workflow_names = args.workflows.split()
    
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
        checker = AutorevertPatternChecker(client, workflow_names=workflow_names, lookback_hours=args.hours)
        
        # Fetch data
        if args.verbose:
            workflows_str = ', '.join(workflow_names)
            print(f"Fetching commits for workflow(s) '{workflows_str}' (last {args.hours}h)...")
        
        # For single workflow, show commit details
        if len(workflow_names) == 1:
            commits = checker.workflow_commits
            
            if not commits:
                print(f"No commit data found for workflow '{workflow_names[0]}' in last {args.hours}h")
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
        else:
            # For multiple workflows, show summary
            if args.verbose:
                print("\nCommit data by workflow:")
                for workflow in workflow_names:
                    commits = checker.get_workflow_commits(workflow)
                    print(f"  {workflow}: {len(commits)} commits")
        
        # Detect patterns
        patterns = checker.detect_autorevert_pattern()
        
        if patterns:
            print(f"✓ {len(patterns)} AUTOREVERT PATTERN{'S' if len(patterns) > 1 else ''} DETECTED")
            
            # Create a revert checker (with extended lookback for finding reverts)
            revert_checker = AutorevertPatternChecker(
                client, 
                workflow_names=[], 
                lookback_hours=args.hours * 2
            )
            
            # Track reverts
            reverted_patterns = []
            
            for i, pattern in enumerate(patterns, 1):
                if len(patterns) > 1:
                    print(f"\nPattern #{i}:")
                
                print(f"Failure rule: '{pattern['failure_rule']}'")
                print(f"Target commit: {pattern['target_commit'][:8]} ({pattern['target_commit_time']})")
                print(f"Failure persisted in {len(pattern['lookahead_commits'])} commits after target")
                print(f"No failure in {pattern['lookback_commits_checked']} commits in 8h before")
                
                # Show additional workflows if detected
                if 'additional_workflows' in pattern:
                    print(f"Also detected in {len(pattern['additional_workflows'])} other workflow(s):")
                    for additional in pattern['additional_workflows']:
                        print(f"  - {additional['workflow_name']}: {additional['failure_rule']}")
                
                # Check if the target commit was reverted
                target_commit = pattern['target_commit']
                revert_result = revert_checker.is_commit_reverted(target_commit)
                
                if revert_result:
                    print(f"✓ REVERTED: {target_commit[:8]} was reverted by {revert_result['revert_sha'][:8]} "
                          f"after {revert_result['hours_after_target']:.1f} hours")
                    reverted_patterns.append(pattern)
                else:
                    print(f"✗ NOT REVERTED: {target_commit[:8]} was not reverted")
                
                if args.verbose:
                    print(f"Failed jobs ({len(pattern['failed_job_names'])}):")
                    for job in pattern['failed_job_names'][:5]:
                        print(f"  - {job}")
                    if len(pattern['failed_job_names']) > 5:
                        print(f"  ... and {len(pattern['failed_job_names']) - 5} more")
                    
                    print(f"Lookahead commits with same failure:")
                    for sha in pattern['lookahead_commits'][:5]:
                        print(f"  - {sha[:8]}")
                    if len(pattern['lookahead_commits']) > 5:
                        print(f"  ... and {len(pattern['lookahead_commits']) - 5} more")
                    
                    if revert_result and args.verbose:
                        print(f"Revert message: {revert_result['revert_message'][:100]}...")
            
            # Print summary statistics
            print("\n" + "="*50)
            print("SUMMARY STATISTICS")
            print("="*50)
            workflows_str = ', '.join(workflow_names)
            print(f"Workflow(s): {workflows_str}")
            print(f"Timeframe: {args.hours} hours")
            
            # Total commits across all workflows
            total_commits = sum(len(checker.get_workflow_commits(w)) for w in workflow_names)
            print(f"Commits checked: {total_commits}")
            
            # Get total revert commits in the period
            total_revert_commits = checker.get_revert_commits()
            print(f"Total revert commits in period: {len(total_revert_commits)}")
            
            print(f"Patterns detected: {len(patterns)}")
            print(f"Actual reverts: {len(reverted_patterns)} ({len(reverted_patterns)/len(patterns)*100:.1f}%)")
            
            if reverted_patterns:
                print(f"\nReverted patterns:")
                for pattern in reverted_patterns:
                    print(f"  - {pattern['failure_rule']}: {pattern['target_commit'][:8]}")
            
            if args.verbose and total_revert_commits:
                print(f"\nAll revert commits in period ({len(total_revert_commits)}):")
                for revert in total_revert_commits[:10]:
                    # Extract the reverted commit SHA from the message
                    match = re.search(r'This reverts commit ([a-f0-9]{40})', revert['message'])
                    reverted_sha = match.group(1)[:8] if match else 'unknown'
                    
                    print(f"  - {revert['sha'][:8]} reverts {reverted_sha}: {revert['message'].split('\\n')[0][:60]}...")
                
                if len(total_revert_commits) > 10:
                    print(f"  ... and {len(total_revert_commits) - 10} more")
            
            return 0
        else:
            print("✗ No autorevert patterns detected")
            
            if args.verbose and len(workflow_names) == 1:
                commits = checker.workflow_commits
                if len(commits) >= 3:
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