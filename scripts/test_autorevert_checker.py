#!/usr/bin/env python3
"""
Test script for AutorevertPatternChecker.
"""

import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from autorevert_checker import AutorevertPatternChecker
import clickhouse_connect
from dotenv import load_dotenv


def main():
    """Test the autorevert pattern checker."""
    load_dotenv()
    
    # Setup ClickHouse client
    client = clickhouse_connect.get_client(
        host=os.getenv('CLICKHOUSE_HOST'),
        port=int(os.getenv('CLICKHOUSE_PORT', 8123)),
        username=os.getenv('CLICKHOUSE_USER'),
        password=os.getenv('CLICKHOUSE_PASSWORD'),
        database='default',
        secure=True
    )
    
    # Test connection
    try:
        result = client.query('SELECT 1')
        print("✓ ClickHouse connection successful")
    except Exception as e:
        print(f"✗ ClickHouse connection failed: {e}")
        return
    
    # Initialize checker
    checker = AutorevertPatternChecker(client)
    
    # Test with a common workflow
    workflow_name = "pull"
    lookback_hours = 168  # Look back 7 days to get more data
    
    print(f"\nFetching recent commits for workflow '{workflow_name}' (last {lookback_hours}h)...")
    
    try:
        commits = checker.get_recent_commits_data(workflow_name, lookback_hours)
        print(f"✓ Found {len(commits)} commits with job data")
        
        if not commits:
            print("No commit data found. Try increasing lookback_hours or different workflow.")
            return
        
        # Show summary of first few commits
        print("\nRecent commits summary:")
        for i, commit in enumerate(commits[:5]):
            failed_count = len(commit.failed_jobs)
            total_count = len(commit.jobs)
            pending = "PENDING" if commit.has_pending_jobs else ""
            print(f"  {i+1}. {commit.head_sha[:8]} ({commit.created_at.strftime('%m-%d %H:%M')}) - "
                  f"{failed_count}/{total_count} failed {pending}")
        
        # Test pattern detection
        print(f"\nTesting autorevert pattern detection...")
        pattern_result = checker.detect_autorevert_pattern(commits)
        
        if pattern_result:
            print("✓ AUTOREVERT PATTERN DETECTED!")
            print(f"  Failure rule: '{pattern_result['failure_rule']}'")
            print(f"  Recent commits with failure: {[sha[:8] for sha in pattern_result['newer_commits']]}")
            print(f"  Older commit without failure: {pattern_result['older_commit'][:8]}")
            print(f"  Failed jobs ({len(pattern_result['failed_job_names'])}): {pattern_result['failed_job_names'][:2]}...")  # Show first 2
            print(f"  Job coverage overlap: {len(pattern_result['older_job_coverage'])} jobs")
            print(f"  Overlapping jobs: {pattern_result['older_job_coverage'][:2]}...")  # Show first 2
        else:
            print("✗ No autorevert pattern detected in current data")
            
            # Show some diagnostic info
            if len(commits) >= 3:
                print(f"\nDiagnostic info (first 3 commits):")
                for i, commit in enumerate(commits[:3]):
                    failures = {j.classification_rule for j in commit.failed_jobs if j.classification_rule}
                    print(f"  Commit {i+1} ({commit.head_sha[:8]}): {len(failures)} unique failures")
                    if failures:
                        print(f"    Rules: {list(failures)[:2]}...")  # Show first 2
        
    except Exception as e:
        print(f"✗ Error during testing: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()