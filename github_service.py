"""GitHub REST API helpers for Akademika content submissions."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

import requests

from content_builder import build_manual_index, manual_index_destination


API_ROOT = 'https://api.github.com'


@dataclass
class GitHubConfig:
    token: str
    owner: str
    repo: str
    base_branch: str
    dry_run: bool = True

    @property
    def repo_full_name(self) -> str:
        return f'{self.owner}/{self.repo}'


class GitHubServiceError(RuntimeError):
    pass


class GitHubService:
    def __init__(self, config: GitHubConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {config.token}',
            'X-GitHub-Api-Version': '2022-11-28',
        })

    def _request(self, method: str, path: str, **kwargs):
        url = f'{API_ROOT}/repos/{self.config.owner}/{self.config.repo}{path}'
        response = self.session.request(method, url, timeout=30, **kwargs)
        if response.status_code >= 400:
            message = response.text
            try:
                message = response.json().get('message', message)
            except ValueError:
                pass
            raise GitHubServiceError(f'GitHub API {method} {path} failed: {response.status_code} {message}')
        if response.status_code == 204:
            return None
        return response.json()

    def get_branch_sha(self, branch: str) -> str:
        data = self._request('GET', f'/git/ref/heads/{branch}')
        return data['object']['sha']

    def get_file_json(self, path: str, branch: str):
        try:
            data = self._request('GET', f'/contents/{path}', params={'ref': branch})
        except GitHubServiceError as exc:
            if '404' in str(exc):
                return None
            raise
        content = base64.b64decode(data.get('content', '')).decode('utf-8')
        return json.loads(content)

    def create_branch(self, branch: str, base_sha: str) -> None:
        self._request('POST', '/git/refs', json={'ref': f'refs/heads/{branch}', 'sha': base_sha})

    def put_file(self, path: str, content: bytes, branch: str, message: str) -> None:
        payload = {
            'message': message,
            'content': base64.b64encode(content).decode('ascii'),
            'branch': branch,
        }
        try:
            existing = self._request('GET', f'/contents/{path}', params={'ref': branch})
            payload['sha'] = existing['sha']
        except GitHubServiceError as exc:
            if '404' not in str(exc):
                raise
        self._request('PUT', f'/contents/{path}', json=payload)

    def create_pull_request(self, branch: str, title: str, body: str):
        return self._request('POST', '/pulls', json={
            'title': title,
            'head': branch,
            'base': self.config.base_branch,
            'body': body,
        })


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')


def make_branch_name(manual_id: str) -> str:
    safe = ''.join(ch if ch.isalnum() or ch in '-_' else '-' for ch in manual_id.strip().lower()).strip('-')
    return f'content/{safe or "manual"}-{timestamp_slug()}'


def build_commit_plan(service: GitHubService, branch: str, manual: Dict, files: Dict[str, bytes]) -> Dict[str, bytes]:
    planned = dict(files)
    existing_index = service.get_file_json(manual_index_destination(), branch)
    index_payload = build_manual_index(existing_index, manual)
    planned[manual_index_destination()] = json.dumps(index_payload, indent=2, ensure_ascii=False).encode('utf-8')
    return planned


def submit_pull_request(config: GitHubConfig, manual: Dict, files: Dict[str, bytes]) -> Dict:
    service = GitHubService(config)
    base_sha = service.get_branch_sha(config.base_branch)
    branch = make_branch_name(manual.get('manualId', 'manual'))

    if config.dry_run:
        planned = build_commit_plan(service, config.base_branch, manual, files)
        return {
            'dry_run': True,
            'branch': branch,
            'base_sha': base_sha,
            'files': sorted(planned),
            'pull_request_url': None,
        }

    service.create_branch(branch, base_sha)
    planned = build_commit_plan(service, branch, manual, files)
    manual_id = manual.get('manualId') or 'manual'
    message = f'Add manual content for {manual_id}'
    for path, content in planned.items():
        service.put_file(path, content, branch, message)

    pr = service.create_pull_request(
        branch,
        title=f'Add manual content for {manual_id}',
        body='Generated manual content submitted from the Akademika Streamlit editor.',
    )
    return {
        'dry_run': False,
        'branch': branch,
        'base_sha': base_sha,
        'files': sorted(planned),
        'pull_request_url': pr.get('html_url'),
    }
