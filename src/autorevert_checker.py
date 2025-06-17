#!/usr/bin/env python3
"""
Autorevert pattern detection for PyTorch CI workflows.

Detects pattern where 2 recent commits have same failure and 1 older doesn't.
"""

import os
import re
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
    
    def __init__(self, client: Client, workflow_name: str = None, lookback_hours: int = 48):
        self.client = client
        self.workflow_name = workflow_name
        self.lookback_hours = lookback_hours
        self._workflow_commits = None
        self._commit_history = None
    
    @property
    def workflow_commits(self) -> List[CommitJobs]:
        """Get workflow commits, fetching if needed."""
        if self._workflow_commits is None and self.workflow_name:
            self._fetch_workflow_data()
        return self._workflow_commits or []
    
    @property
    def commit_history(self) -> List[Dict]:
        """Get commit history, fetching if needed."""
        if self._commit_history is None:
            self._fetch_commit_history()
        return self._commit_history or []
    
    def _fetch_workflow_data(self):
        """Fetch workflow job data from ClickHouse."""
        lookback_time = datetime.now() - timedelta(hours=self.lookback_hours)

        print(f"Fetching workflow data for '{self.workflow_name}' since {lookback_time.isoformat()}...")
        
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
                'workflow_name': self.workflow_name,
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

        print(f"Found {len(commits_data)} commits with job data for workflow '{self.workflow_name}'")
        
        # Sort by creation time (newest first)
        self._workflow_commits = sorted(commits_data.values(), key=lambda c: c.created_at, reverse=True)
    
    def _fetch_commit_history(self):
        """Fetch commit history from push table."""
        lookback_time = datetime.now() - timedelta(hours=self.lookback_hours)
        
        query = """
        SELECT DISTINCT
            head_commit.id as sha,
            head_commit.message as message,
            head_commit.timestamp as timestamp
        FROM default.push 
        WHERE head_commit.timestamp >= {lookback_time:DateTime}
          AND ref = 'refs/heads/main'
        ORDER BY head_commit.timestamp DESC
        """
        
        result = self.client.query(
            query,
            parameters={'lookback_time': lookback_time}
        )
        
        self._commit_history = [
            {
                'sha': row[0],
                'message': row[1],
                'timestamp': row[2]
            }
            for row in result.result_rows
        ]
    
    def detect_autorevert_pattern(self) -> List[Dict]:
        """
        Detect all autorevert patterns in commit job data.
        
        Pattern: 3 consecutive commits where:
        - 2 newer commits have same exact failure classification
        - 1 older commit doesn't have this failure but has matching jobs
        - All commits have signal (jobs present) and no pending jobs in oldest
        
        Returns:
            List of all detected patterns
        """
        commits = self.workflow_commits
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
    
    def is_commit_reverted(self, target_commit_sha: str) -> Optional[Dict]:
        """
        Check if a commit was reverted within the lookback window.
        
        Args:
            target_commit_sha: The commit to check for reverting
        
        Returns:
            Dict with revert information if found, None otherwise
        """
        commits = self.commit_history
        target_time = None
        
        # Find target commit timestamp
        for commit in commits:
            if commit['sha'] == target_commit_sha:
                target_time = commit['timestamp']
                break
        
        if not target_time:
            return None  # Target commit not found
        
        # Look for revert commits after target commit
        for commit in commits:
            commit_time = commit['timestamp']
            
            # Only consider commits after target
            if commit_time <= target_time:
                continue
            
            message = commit['message']
            
            # Check for revert pattern
            if message.startswith('Revert "') and f"This reverts commit {target_commit_sha}" in message:
                return {
                    'reverted': True,
                    'revert_sha': commit['sha'],
                    'revert_message': message,
                    'revert_timestamp': commit_time,
                    'hours_after_target': (commit_time - target_time).total_seconds() / 3600
                }
        
        return None  # No revert found


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