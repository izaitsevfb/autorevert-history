#!/usr/bin/env python3
"""
Autorevert pattern detection for PyTorch CI workflows.

Detects optimistic pattern where a failure appears on a commit that:
- Did NOT have this failure in the 8 hours before
- DOES have this failure on the target commit
- Also has this failure in commits within 8 hours after
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
    
    def __init__(self, client: Client, workflow_names: List[str] = None, lookback_hours: int = 48):
        self.client = client
        self.workflow_names = workflow_names or []
        self.lookback_hours = lookback_hours
        self._workflow_commits_cache = {}  # Dict[str, List[CommitJobs]]
        self._commit_history = None
    
    def get_workflow_commits(self, workflow_name: str) -> List[CommitJobs]:
        """Get workflow commits for a specific workflow, fetching if needed."""
        if workflow_name not in self._workflow_commits_cache:
            self._fetch_workflow_data()
        return self._workflow_commits_cache.get(workflow_name, [])
    
    @property
    def workflow_commits(self) -> List[CommitJobs]:
        """Get workflow commits for the first workflow (backward compatibility)."""
        if self.workflow_names:
            return self.get_workflow_commits(self.workflow_names[0])
        return []
    
    @property
    def commit_history(self) -> List[Dict]:
        """Get commit history, fetching if needed."""
        if self._commit_history is None:
            self._fetch_commit_history()
        return self._commit_history or []
    
    def _fetch_workflow_data(self):
        """Fetch workflow job data from ClickHouse for all workflows in batch."""
        if not self.workflow_names:
            return
            
        lookback_time = datetime.now() - timedelta(hours=self.lookback_hours)

        print(f"Fetching workflow data for {len(self.workflow_names)} workflows since {lookback_time.isoformat()}...")
        
        query = """
        SELECT 
            workflow_name,
            head_sha,
            name,
            conclusion,
            status,
            torchci_classification.rule as classification_rule,
            workflow_created_at
        FROM workflow_job FINAL
        WHERE workflow_name IN {workflow_names:Array(String)}
          AND head_branch = 'main'
          AND workflow_created_at >= {lookback_time:DateTime}
        ORDER BY workflow_name, workflow_created_at DESC, head_sha, name
        """
        
        result = self.client.query(
            query,
            parameters={
                'workflow_names': self.workflow_names,
                'lookback_time': lookback_time
            }
        )
        
        # Group by workflow and commit SHA
        workflow_commits_data = {}
        for row in result.result_rows:
            workflow_name, head_sha, name, conclusion, status, classification_rule, created_at = row
            
            if workflow_name not in workflow_commits_data:
                workflow_commits_data[workflow_name] = {}
            
            if head_sha not in workflow_commits_data[workflow_name]:
                workflow_commits_data[workflow_name][head_sha] = CommitJobs(
                    head_sha=head_sha,
                    created_at=created_at,
                    jobs=[]
                )
            
            workflow_commits_data[workflow_name][head_sha].jobs.append(JobResult(
                head_sha=head_sha,
                name=name,
                conclusion=conclusion,
                status=status,
                classification_rule=classification_rule or '',
                workflow_created_at=created_at
            ))

        # Sort and cache results per workflow
        for workflow_name, commits_data in workflow_commits_data.items():
            print(f"Found {len(commits_data)} commits with job data for workflow '{workflow_name}'")
            self._workflow_commits_cache[workflow_name] = sorted(
                commits_data.values(), 
                key=lambda c: c.created_at, 
                reverse=True
            )
        
        # Initialize empty lists for workflows with no data
        for workflow_name in self.workflow_names:
            if workflow_name not in self._workflow_commits_cache:
                self._workflow_commits_cache[workflow_name] = []
    
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
    
    def detect_autorevert_pattern_workflow(self, workflow_name: str) -> List[Dict]:
        """
        Detect optimistic autorevert patterns in commit job data for a specific workflow.
        
        Pattern: Target commit with failure line where:
        - Lookback: failure line NOT present in 8 hours before target commit
        - Target: failure line IS present on the target commit
        - Lookahead: failure line IS also present in any commits in 8 hours after
        
        Args:
            workflow_name: The workflow to analyze
            
        Returns:
            List of all detected patterns
        """
        commits = self.get_workflow_commits(workflow_name)
        if not commits:
            return []
        
        patterns = []
        lookback_hours = 8
        lookahead_hours = 8
        
        # Process each commit as a potential target
        for i, target_commit in enumerate(commits):
            # Skip if target has no failures
            if not target_commit.failed_jobs:
                continue
                
            # Skip if target has pending jobs
            if target_commit.has_pending_jobs:
                continue
            
            target_time = target_commit.created_at
            
            # Get all failure rules in target commit
            target_failures = {j.classification_rule for j in target_commit.failed_jobs}
            
            for failure_rule in target_failures:
                # Get commits in lookback window (8 hours before)
                lookback_commits = []
                for j in range(i + 1, len(commits)):
                    commit = commits[j]
                    time_diff = (target_time - commit.created_at).total_seconds() / 3600
                    if time_diff > lookback_hours:
                        break
                    lookback_commits.append(commit)
                
                # Get commits in lookahead window (8 hours after)
                lookahead_commits = []
                for j in range(i - 1, -1, -1):
                    commit = commits[j]
                    time_diff = (commit.created_at - target_time).total_seconds() / 3600
                    if time_diff > lookahead_hours:
                        break
                    lookahead_commits.append(commit)
                
                # Check lookback: failure should NOT be present
                failure_in_lookback = False
                for commit in lookback_commits:
                    if any(j.classification_rule == failure_rule for j in commit.failed_jobs):
                        failure_in_lookback = True
                        break
                
                if failure_in_lookback:
                    continue  # Skip this failure rule, it was present before
                
                # Check lookahead: failure SHOULD be present in at least one commit
                lookahead_commits_with_failure = []
                for commit in lookahead_commits:
                    if any(j.classification_rule == failure_rule for j in commit.failed_jobs):
                        lookahead_commits_with_failure.append(commit.head_sha)
                
                if not lookahead_commits_with_failure:
                    continue  # Skip this failure rule, it doesn't persist after
                
                # Pattern detected!
                # Get job names that had this failure
                failed_job_names = []
                for job in target_commit.failed_jobs:
                    if job.classification_rule == failure_rule:
                        failed_job_names.append(target_commit.normalize_job_name(job.name))
                
                patterns.append({
                    'pattern_detected': True,
                    'workflow_name': workflow_name,
                    'failure_rule': failure_rule,
                    'target_commit': target_commit.head_sha,
                    'target_commit_time': target_time.isoformat(),
                    'lookahead_commits': lookahead_commits_with_failure,
                    'failed_job_names': failed_job_names,
                    'lookback_window_hours': lookback_hours,
                    'lookahead_window_hours': lookahead_hours,
                    'lookback_commits_checked': len(lookback_commits),
                    'lookahead_commits_checked': len(lookahead_commits)
                })
        
        return patterns
    
    def detect_autorevert_pattern(self) -> List[Dict]:
        """
        Detect all autorevert patterns across all configured workflows.
        
        When the same target commit is detected across multiple workflows, the pattern
        is kept once with the first workflow, and other workflows are added to
        an 'additional_workflows' field.
        
        Returns:
            List of all detected patterns from all workflows (deduplicated)
        """
        all_patterns = []
        seen_target_commits = {}  # Map of target_commit -> pattern index
        
        for workflow_name in self.workflow_names:
            patterns = self.detect_autorevert_pattern_workflow(workflow_name)
            
            for pattern in patterns:
                # Use target commit as the deduplication key
                target_commit = pattern['target_commit']
                
                if target_commit in seen_target_commits:
                    # Add this workflow to the existing pattern's additional_workflows
                    pattern_idx = seen_target_commits[target_commit]
                    existing_pattern = all_patterns[pattern_idx]
                    
                    if 'additional_workflows' not in existing_pattern:
                        existing_pattern['additional_workflows'] = []
                    
                    existing_pattern['additional_workflows'].append({
                        'workflow_name': workflow_name,
                        'failure_rule': pattern['failure_rule']
                    })
                else:
                    # First time seeing this target commit
                    seen_target_commits[target_commit] = len(all_patterns)
                    all_patterns.append(pattern)
        
        return all_patterns
    
    def is_revert_commit(self, commit: Dict) -> bool:
        """
        Check if a commit is a revert commit based on its message.
        
        Args:
            commit: Dict with 'message' field
            
        Returns:
            True if the commit is a revert, False otherwise
        """
        message = commit.get('message', '')
        return message.startswith('Revert "') and 'This reverts commit' in message
    
    def get_revert_commits(self) -> List[Dict]:
        """
        Get all revert commits from the commit history.
        
        Returns:
            List of revert commits
        """
        return [commit for commit in self.commit_history if self.is_revert_commit(commit)]
    
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