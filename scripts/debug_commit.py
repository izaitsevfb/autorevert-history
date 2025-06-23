#!/usr/bin/env python3
"""
Debug tool for analyzing autorevert patterns for a specific commit.

Shows detailed failure information and why a pattern was or wasn't detected.
"""

import argparse
import os
import sys
from datetime import timedelta
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from autorevert_checker import create_clickhouse_client, AutorevertPatternChecker


def format_job_failure(job):
    """Format a job failure with details."""
    return f"  - {job.name}\n    Rule: {job.classification_rule}\n    Conclusion: {job.conclusion}"


def analyze_commit_context(checker, workflow_name, target_sha, window_hours=8):
    """Analyze commits around the target commit."""
    commits = checker.get_workflow_commits(workflow_name)
    
    # Find target commit index (support partial SHA matching)
    target_idx = None
    target_commit = None
    for i, commit in enumerate(commits):
        if commit.head_sha.startswith(target_sha):
            target_idx = i
            target_commit = commit
            break
    
    if target_idx is None:
        return None, [], []
    
    # Get commits in lookback and lookahead windows
    lookback_commits = []
    lookahead_commits = []
    
    if target_commit:
        target_time = target_commit.created_at
        
        # Lookback window
        for j in range(target_idx + 1, len(commits)):
            commit = commits[j]
            time_diff = (target_time - commit.created_at).total_seconds() / 3600
            if time_diff > window_hours:
                break
            lookback_commits.append(commit)
        
        # Lookahead window
        for j in range(target_idx - 1, -1, -1):
            commit = commits[j]
            time_diff = (commit.created_at - target_time).total_seconds() / 3600
            if time_diff > window_hours:
                break
            lookahead_commits.append(commit)
    
    return target_commit, lookback_commits, lookahead_commits


def main():
    """CLI interface for debugging specific commit patterns."""
    parser = argparse.ArgumentParser(
        description="Debug autorevert pattern detection for a specific commit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s f179b719 pull
  %(prog)s c79c7bbe pull,trunk,inductor
  %(prog)s 18e42406 "pull trunk" --window 12
  %(prog)s d83636de pull --hours 72 --show-all-failures
        """
    )
    
    parser.add_argument(
        'commit',
        help='Commit SHA to analyze (can be short or full)'
    )
    parser.add_argument(
        'workflows',
        help='Workflow name(s) to analyze - comma or space separated'
    )
    parser.add_argument(
        '--window',
        type=int,
        default=8,
        help='Window size in hours for lookback/lookahead (default: 8)'
    )
    parser.add_argument(
        '--hours',
        type=int,
        default=48,
        help='Lookback window in hours for fetching commits (default: 48)'
    )
    parser.add_argument(
        '--show-all-failures',
        action='store_true',
        help='Show all failure types in surrounding commits'
    )
    
    args = parser.parse_args()
    
    # Parse workflow names
    workflow_names = []
    if ',' in args.workflows:
        workflow_names = [w.strip() for w in args.workflows.split(',')]
    else:
        workflow_names = args.workflows.split()
    
    # Normalize commit SHA (remove any 'g' prefix from git describe)
    target_sha = args.commit.lstrip('g')
    
    try:
        # Initialize checker with configurable lookback
        client = create_clickhouse_client()
        checker = AutorevertPatternChecker(
            client, 
            workflow_names=workflow_names, 
            lookback_hours=args.hours
        )
        
        print(f"Analyzing commit {target_sha} in workflow(s): {', '.join(workflow_names)}")
        print(f"Using {args.window}-hour lookback/lookahead windows")
        print("=" * 80)
        
        # Try to detect patterns for this specific commit
        all_patterns = checker.detect_autorevert_pattern()
        
        # Find patterns matching our target commit
        matching_patterns = []
        for pattern in all_patterns:
            if pattern['target_commit'].startswith(target_sha):
                matching_patterns.append(pattern)
        
        if matching_patterns:
            print(f"\n✓ PATTERN DETECTED for commit {target_sha}")
            
            for i, pattern in enumerate(matching_patterns, 1):
                if len(matching_patterns) > 1:
                    print(f"\nPattern #{i}:")
                
                print(f"\nWorkflow: {pattern['workflow_name']}")
                print(f"Failure rule: '{pattern['failure_rule']}'")
                print(f"Target commit: {pattern['target_commit']} ({pattern['target_commit_time']})")
                print(f"Lookback: No failure in {pattern['lookback_commits_checked']} commits in {pattern['lookback_window_hours']}h before")
                print(f"Lookahead: Failure persisted in {len(pattern['lookahead_commits'])} commits in {pattern['lookahead_window_hours']}h after")
                
                # Get detailed failure information
                workflow_name = pattern['workflow_name']
                target_commit, lookback_commits, lookahead_commits = analyze_commit_context(
                    checker, workflow_name, pattern['target_commit'], args.window
                )
                
                if target_commit:
                    print(f"\nFailed jobs on target commit ({len(pattern['failed_job_names'])}):")
                    for job in target_commit.failed_jobs:
                        if job.classification_rule == pattern['failure_rule']:
                            print(format_job_failure(job))
                    
                    print(f"\nLookahead commits with same failure:")
                    for sha in pattern['lookahead_commits']:
                        # Find the commit details
                        for commit in lookahead_commits:
                            if commit.head_sha == sha:
                                matching_jobs = [j for j in commit.failed_jobs 
                                               if j.classification_rule == pattern['failure_rule']]
                                print(f"  {sha[:8]} ({commit.created_at.strftime('%m-%d %H:%M')}) - "
                                      f"{len(matching_jobs)} jobs with same failure")
                                break
                
                if 'additional_workflows' in pattern:
                    print(f"\nAlso detected in {len(pattern['additional_workflows'])} other workflow(s):")
                    for additional in pattern['additional_workflows']:
                        print(f"  - {additional['workflow_name']}: {additional['failure_rule']}")
        
        else:
            print(f"\n✗ NO PATTERN DETECTED for commit {target_sha}")
            print("\nAnalyzing why pattern was not detected...")
            
            # Analyze each workflow
            for workflow_name in workflow_names:
                print(f"\n--- Workflow: {workflow_name} ---")
                
                target_commit, lookback_commits, lookahead_commits = analyze_commit_context(
                    checker, workflow_name, target_sha, args.window
                )
                
                if not target_commit:
                    print(f"  Commit {target_sha} not found in this workflow")
                    continue
                
                print(f"\nTarget commit {target_sha[:8]} ({target_commit.created_at.strftime('%Y-%m-%d %H:%M')})")
                
                if not target_commit.failed_jobs:
                    print("  ✗ No failures on target commit (pattern requires failures)")
                elif target_commit.has_pending_jobs:
                    print("  ✗ Has pending jobs (pattern requires completed jobs)")
                else:
                    print(f"  ✓ Has {len(target_commit.failed_jobs)} failures:")
                    failure_rules = {}
                    for job in target_commit.failed_jobs:
                        rule = job.classification_rule
                        if rule not in failure_rules:
                            failure_rules[rule] = []
                        failure_rules[rule].append(job)
                    
                    for rule, jobs in failure_rules.items():
                        print(f"\n  Failure rule: '{rule}' ({len(jobs)} jobs)")
                        
                        # Check lookback
                        lookback_has_failure = False
                        for commit in lookback_commits:
                            if any(j.classification_rule == rule for j in commit.failed_jobs):
                                lookback_has_failure = True
                                print(f"    ✗ Lookback: Found same failure {(target_commit.created_at - commit.created_at).total_seconds() / 3600:.1f}h before at {commit.head_sha[:8]}")
                                break
                        
                        if not lookback_has_failure:
                            print(f"    ✓ Lookback: No failure in {len(lookback_commits)} commits ({args.window}h window)")
                        
                        # Check lookahead
                        lookahead_has_failure = []
                        for commit in lookahead_commits:
                            if any(j.classification_rule == rule for j in commit.failed_jobs):
                                lookahead_has_failure.append(commit.head_sha[:8])
                        
                        if lookahead_has_failure:
                            print(f"    ✓ Lookahead: Found in {len(lookahead_has_failure)} commits: {', '.join(lookahead_has_failure[:5])}")
                        else:
                            print(f"    ✗ Lookahead: Not found in {len(lookahead_commits)} commits ({args.window}h window)")
                        
                        # If pattern should have been detected but wasn't, investigate why
                        if not lookback_has_failure and lookahead_has_failure:
                            print("    ⚠️  Pattern criteria met but not detected - possible edge case")
                
                if args.show_all_failures or target_commit.failed_jobs:
                    print(f"\nSurrounding commits analysis:")
                    
                    # Show lookback commits
                    if lookback_commits:
                        print(f"\nLookback ({len(lookback_commits)} commits in {args.window}h before):")
                        for i, commit in enumerate(lookback_commits[:5]):
                            time_diff = (target_commit.created_at - commit.created_at).total_seconds() / 3600
                            if commit.failed_jobs:
                                print(f"  {commit.head_sha[:8]} (-{time_diff:.1f}h) - {len(commit.failed_jobs)} failures")
                                if args.show_all_failures:
                                    for job in commit.failed_jobs[:3]:
                                        print(f"    - {job.classification_rule}")
                            else:
                                print(f"  {commit.head_sha[:8]} (-{time_diff:.1f}h) - ✓ no failures")
                    
                    # Show lookahead commits  
                    if lookahead_commits:
                        print(f"\nLookahead ({len(lookahead_commits)} commits in {args.window}h after):")
                        for i, commit in enumerate(lookahead_commits[:5]):
                            time_diff = (commit.created_at - target_commit.created_at).total_seconds() / 3600
                            if commit.failed_jobs:
                                print(f"  {commit.head_sha[:8]} (+{time_diff:.1f}h) - {len(commit.failed_jobs)} failures")
                                if args.show_all_failures:
                                    for job in commit.failed_jobs[:3]:
                                        print(f"    - {job.classification_rule}")
                            else:
                                print(f"  {commit.head_sha[:8]} (+{time_diff:.1f}h) - ✓ no failures")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())