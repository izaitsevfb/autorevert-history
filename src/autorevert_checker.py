#!/usr/bin/env python3
"""
Autorevert pattern detection for PyTorch CI workflows.

Detects pattern where 2 recent commits have same failure and 1 older doesn't.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta

import clickhouse_connect
from clickhouse_connect.driver import Client
from dotenv import load_dotenv


@dataclass
class JobResult:
    """Job execution result with classification."""
    head_sha: str
    name: str
    conclusion: str
    status: str
    classification_rule: str
    workflow_created_at: datetime


@dataclass 
class CommitJobs:
    """All jobs for a single commit."""
    head_sha: str
    created_at: datetime
    jobs: List[JobResult]
    
    @property
    def failed_jobs(self) -> List[JobResult]:
        """Jobs with failure conclusion and classification rule."""
        return [j for j in self.jobs if j.conclusion == 'failure' and j.classification_rule]
    
    @property
    def has_pending_jobs(self) -> bool:
        """Check if any jobs are still pending."""
        return any(j.status == 'pending' for j in self.jobs)
    
    def normalize_job_name(self, name: str) -> str:
        """Strip shard suffix from job name for matching."""
        # Remove patterns like ", 1, 1, " or ", 2, 3, " from job names
        return re.sub(r', \d+, \d+, ', ', ', name)
    
    def get_job_base_names(self) -> Set[str]:
        """Get normalized job names (without shard info)."""
        return {self.normalize_job_name(j.name) for j in self.jobs}


class AutorevertPatternChecker:
    """Detects autorevert patterns in workflow job failures."""
    
    def __init__(self, client: Client):
        self.client = client
    
    def get_recent_commits_data(self, workflow_name: str, lookback_hours: int = 24) -> List[CommitJobs]:
        """
        Fetch recent commit job data with simple ClickHouse query.
        """
        lookback_time = datetime.now() - timedelta(hours=lookback_hours)
        
        query = """
        SELECT 
            head_sha,
            name,
            conclusion,
            status,
            torchci_classification.rule as classification_rule,
            workflow_created_at
        FROM workflow_job FINAL
        WHERE workflow_name = {workflow_name:String}
          AND head_branch = 'main'
          AND workflow_created_at >= {lookback_time:DateTime}
        ORDER BY workflow_created_at DESC, head_sha, name
        """
        
        result = self.client.query(
            query,
            parameters={
                'workflow_name': workflow_name,
                'lookback_time': lookback_time
            }
        )
        
        # Group by commit SHA
        commits_data = {}
        for row in result.result_rows:
            head_sha, name, conclusion, status, classification_rule, created_at = row
            
            if head_sha not in commits_data:
                commits_data[head_sha] = CommitJobs(
                    head_sha=head_sha,
                    created_at=created_at,
                    jobs=[]
                )
            
            commits_data[head_sha].jobs.append(JobResult(
                head_sha=head_sha,
                name=name,
                conclusion=conclusion,
                status=status,
                classification_rule=classification_rule or '',
                workflow_created_at=created_at
            ))
        
        # Sort by creation time (newest first)
        return sorted(commits_data.values(), key=lambda c: c.created_at, reverse=True)
    
    def detect_autorevert_pattern(self, commits: List[CommitJobs]) -> List[Dict]:
        """
        Detect all autorevert patterns in commit job data.
        
        Pattern: 3 consecutive commits where:
        - 2 newer commits have same exact failure classification
        - 1 older commit doesn't have this failure but has matching jobs
        - All commits have signal (jobs present) and no pending jobs in oldest
        
        Returns:
            List of all detected patterns
        """
        if len(commits) < 3:
            return []
        
        patterns = []
        
        for i in range(len(commits) - 2):
            newer_commit1 = commits[i]      # Most recent
            newer_commit2 = commits[i + 1]  # Second most recent  
            older_commit = commits[i + 2]   # Third most recent
            
            # All commits must have jobs (signal)
            if not all(c.jobs for c in [newer_commit1, newer_commit2, older_commit]):
                continue
                
            # Oldest commit cannot have pending jobs
            if older_commit.has_pending_jobs:
                continue
            
            # Find common failure classifications between the 2 newer commits
            newer1_failures = {j.classification_rule for j in newer_commit1.failed_jobs}
            newer2_failures = {j.classification_rule for j in newer_commit2.failed_jobs}
            common_failures = newer1_failures & newer2_failures
            
            if not common_failures:
                continue
            
            # Check if older commit lacks these failures but has overlapping job coverage
            older_failures = {j.classification_rule for j in older_commit.failed_jobs}
            older_job_names = older_commit.get_job_base_names()
            
            for failure_rule in common_failures:
                if failure_rule in older_failures:
                    continue  # Older commit also has this failure
                
                # Get job names that had this failure in newer commits
                failed_job_names = set()
                for commit in [newer_commit1, newer_commit2]:
                    for job in commit.failed_jobs:
                        if job.classification_rule == failure_rule:
                            failed_job_names.add(commit.normalize_job_name(job.name))
                
                # Check if older commit has overlapping job coverage
                if failed_job_names & older_job_names:
                    patterns.append({
                        'pattern_detected': True,
                        'failure_rule': failure_rule,
                        'newer_commits': [newer_commit1.head_sha, newer_commit2.head_sha],
                        'older_commit': older_commit.head_sha,
                        'failed_job_names': list(failed_job_names),
                        'older_job_coverage': list(older_job_names & failed_job_names)
                    })
        
        return patterns


def create_clickhouse_client() -> Client:
    """Create ClickHouse client with environment variables."""
    load_dotenv()
    return clickhouse_connect.get_client(
        host=os.getenv('CLICKHOUSE_HOST'),
        port=int(os.getenv('CLICKHOUSE_PORT', 8123)),
        username=os.getenv('CLICKHOUSE_USER'),
        password=os.getenv('CLICKHOUSE_PASSWORD'),
        database='default',
        secure=True
    )


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
        nargs='?',
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
    
    # Workflow argument is required for non-test operations
    if not args.workflow:
        parser.error("workflow argument is required (unless using --test-connection)")
        return 1
    
    try:
        # Initialize checker
        client = create_clickhouse_client()
        checker = AutorevertPatternChecker(client)
        
        # Fetch data
        if args.verbose:
            print(f"Fetching commits for workflow '{args.workflow}' (last {args.hours}h)...")
        
        commits = checker.get_recent_commits_data(args.workflow, args.hours)
        
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
        patterns = checker.detect_autorevert_pattern(commits)
        
        if patterns:
            print(f"✓ {len(patterns)} AUTOREVERT PATTERN{'S' if len(patterns) > 1 else ''} DETECTED")
            
            for i, pattern in enumerate(patterns, 1):
                if len(patterns) > 1:
                    print(f"\nPattern #{i}:")
                print(f"Failure rule: '{pattern['failure_rule']}'")
                print(f"Recent commits with failure: {' '.join(sha[:8] for sha in pattern['newer_commits'])}")
                print(f"Older commit without failure: {pattern['older_commit'][:8]}")
                
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