"""
Shared module for restarting PyTorch workflows via GitHub API.
"""

import os
import requests
import logging
from typing import Optional, Dict, Any


class WorkflowRestarter:
    """Handle restarting PyTorch workflows using GitHub API."""
    
    def __init__(self, github_token: str, repo_owner: str = "pytorch", repo_name: str = "pytorch"):
        """
        Initialize WorkflowRestarter.
        
        Args:
            github_token: GitHub personal access token with workflow permissions
            repo_owner: Repository owner (default: pytorch)
            repo_name: Repository name (default: pytorch)
        """
        self.github_token = github_token
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        self.headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.logger = logging.getLogger(__name__)
    
    def restart_workflow_for_commit(
        self, 
        workflow_name: str, 
        commit_sha: str, 
        inputs: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Restart a PyTorch workflow for a specific commit SHA.
        
        Args:
            workflow_name: Name of the workflow file (e.g., "trunk.yml")
            commit_sha: The commit SHA to restart workflow for
            inputs: Optional workflow inputs
            
        Returns:
            bool: True if workflow was successfully dispatched, False otherwise
        """
        try:
            # Create tag reference for the commit SHA
            tag_ref = f"trunk/{commit_sha}"
            
            # First, create the tag if it doesn't exist
            if not self._tag_exists(tag_ref):
                if not self._create_tag(tag_ref, commit_sha):
                    self.logger.error(f"Failed to create tag {tag_ref}")
                    return False
            
            # Dispatch the workflow using the tag
            return self._dispatch_workflow(workflow_name, tag_ref, inputs)
            
        except Exception as e:
            self.logger.error(f"Error restarting workflow {workflow_name} for commit {commit_sha}: {e}")
            return False
    
    def _tag_exists(self, tag_ref: str) -> bool:
        """Check if a tag exists in the repository."""
        try:
            url = f"{self.base_url}/git/refs/tags/{tag_ref}"
            response = requests.get(url, headers=self.headers)
            return response.status_code == 200
        except Exception as e:
            self.logger.warning(f"Error checking if tag exists: {e}")
            return False
    
    def _create_tag(self, tag_ref: str, commit_sha: str) -> bool:
        """Create a lightweight tag for the given commit SHA."""
        try:
            url = f"{self.base_url}/git/refs"
            data = {
                "ref": f"refs/tags/{tag_ref}",
                "sha": commit_sha
            }
            
            response = requests.post(url, headers=self.headers, json=data)
            
            if response.status_code == 201:
                self.logger.info(f"Created tag {tag_ref} for commit {commit_sha}")
                return True
            else:
                self.logger.error(f"Failed to create tag {tag_ref}: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error creating tag {tag_ref}: {e}")
            return False
    
    def _dispatch_workflow(self, workflow_name: str, ref: str, inputs: Optional[Dict[str, Any]] = None) -> bool:
        """Dispatch a workflow using workflow_dispatch event."""
        try:
            url = f"{self.base_url}/actions/workflows/{workflow_name}/dispatches"
            data = {
                "ref": ref,
                "inputs": inputs or {}
            }
            
            response = requests.post(url, headers=self.headers, json=data)
            
            if response.status_code == 204:
                self.logger.info(f"Successfully dispatched workflow {workflow_name} for ref {ref}")
                return True
            else:
                self.logger.error(f"Failed to dispatch workflow {workflow_name}: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error dispatching workflow {workflow_name}: {e}")
            return False
    
    def get_workflow_runs(self, workflow_name: str, limit: int = 10) -> list:
        """Get recent workflow runs for a given workflow."""
        try:
            url = f"{self.base_url}/actions/workflows/{workflow_name}/runs"
            params = {"per_page": limit}
            
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code == 200:
                return response.json().get("workflow_runs", [])
            else:
                self.logger.error(f"Failed to get workflow runs: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            self.logger.error(f"Error getting workflow runs: {e}")
            return []


def create_workflow_restarter(github_token: Optional[str] = None) -> WorkflowRestarter:
    """
    Factory function to create a WorkflowRestarter instance.
    
    Args:
        github_token: GitHub token, will use GITHUB_TOKEN env var if not provided
        
    Returns:
        WorkflowRestarter instance
        
    Raises:
        ValueError: If no GitHub token is provided
    """
    token = github_token or os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GitHub token is required. Set GITHUB_TOKEN environment variable or pass token directly.")
    
    return WorkflowRestarter(token)