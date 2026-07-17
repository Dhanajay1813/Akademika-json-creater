"""GitHub REST API helpers for Akademika content submissions."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict

import requests

from content_builder import build_manual_index, manual_index_destination
from catalog_builder import build_catalog_index, catalog_index_path


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

    def check_repository_access(self) -> None:
        try:
            self._request('GET', '')
        except GitHubServiceError as exc:
            if '404' in str(exc):
                raise GitHubServiceError(
                    f'GitHub repository {self.config.repo_full_name} was not found or the configured token cannot access it. '
                    'Check github.owner, github.mobile_repo, and token repository permissions.'
                ) from exc
            raise

    def get_branch_sha(self, branch: str) -> str:
        try:
            data = self._request('GET', f'/git/ref/heads/{branch}')
        except GitHubServiceError as exc:
            if '404' in str(exc):
                raise GitHubServiceError(
                    f'Base branch {branch} was not found in {self.config.repo_full_name}, or the token cannot read it.'
                ) from exc
            raise
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

    def create_unique_branch(self, branch: str, base_sha: str) -> str:
        for attempt in range(1, 11):
            candidate = branch if attempt == 1 else f'{branch}-{attempt}'
            try:
                self.create_branch(candidate, base_sha)
                return candidate
            except GitHubServiceError as exc:
                if '422' in str(exc) and 'Reference already exists' in str(exc):
                    continue
                raise
        raise GitHubServiceError(f'Could not create a unique branch after 10 attempts from {branch}.')

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


def safe_branch_part(value: str, fallback: str) -> str:
    safe = ''.join(ch if ch.isalnum() or ch in '-_' else '-' for ch in value.strip().lower()).strip('-')
    return safe or fallback


def make_branch_name(manual_id: str) -> str:
    return f'content/{safe_branch_part(manual_id, "manual")}-{timestamp_slug()}'


def make_catalog_branch_name(product_id: str) -> str:
    return f'catalog/{safe_branch_part(product_id, "product")}-{timestamp_slug()}'


def build_commit_plan(service: GitHubService, branch: str, manual: Dict, files: Dict[str, bytes]) -> Dict[str, bytes]:
    planned = dict(files)
    existing_index = service.get_file_json(manual_index_destination(), branch)
    index_payload = build_manual_index(existing_index, manual)
    planned[manual_index_destination()] = json.dumps(index_payload, indent=2, ensure_ascii=False).encode('utf-8')
    return planned


def build_dry_run_plan(manual: Dict, files: Dict[str, bytes]) -> Dict[str, bytes]:
    planned = dict(files)
    index_payload = build_manual_index(None, manual)
    planned[manual_index_destination()] = json.dumps(index_payload, indent=2, ensure_ascii=False).encode('utf-8')
    return planned


def submit_pull_request(config: GitHubConfig, manual: Dict, files: Dict[str, bytes]) -> Dict:
    branch = make_branch_name(manual.get('manualId', 'manual'))

    if config.dry_run:
        planned = build_dry_run_plan(manual, files)
        return {
            'dry_run': True,
            'branch': branch,
            'base_sha': None,
            'files': sorted(planned),
            'pull_request_url': None,
        }

    service = GitHubService(config)
    service.check_repository_access()
    base_sha = service.get_branch_sha(config.base_branch)
    branch = service.create_unique_branch(branch, base_sha)
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



def build_catalog_commit_plan(service: GitHubService, branch: str, catalog_entry: Dict, files: Dict[str, bytes]) -> Dict[str, bytes]:
    planned = dict(files)
    existing_index = service.get_file_json(catalog_index_path(), branch)
    index_payload = build_catalog_index(existing_index, catalog_entry)
    planned[catalog_index_path()] = json.dumps(index_payload, indent=2, ensure_ascii=False).encode('utf-8')
    return planned


def submit_catalog_pull_request(config: GitHubConfig, metadata: Dict, files: Dict[str, bytes], catalog_entry: Dict) -> Dict:
    branch = make_catalog_branch_name(metadata.get('productId', 'product'))

    if config.dry_run:
        planned = dict(files)
        return {
            'dry_run': True,
            'branch': branch,
            'base_sha': None,
            'files': sorted(planned),
            'pull_request_url': None,
            'is_update': False,
        }

    service = GitHubService(config)
    service.check_repository_access()
    base_sha = service.get_branch_sha(config.base_branch)
    existing_index = service.get_file_json(catalog_index_path(), config.base_branch)
    is_update = bool((existing_index or {}).get('catalogs', {}).get(catalog_entry['catalogId']))
    branch = service.create_unique_branch(branch, base_sha)
    planned = build_catalog_commit_plan(service, branch, catalog_entry, files)
    product_name = metadata.get('productName') or metadata.get('productId') or 'product'
    message = f'Add catalog for {product_name}'
    for path, content in planned.items():
        service.put_file(path, content, branch, message)

    pr = service.create_pull_request(
        branch,
        title=f'Add catalog for {product_name}',
        body='Generated product catalog submitted from the Akademika Streamlit editor.',
    )
    return {
        'dry_run': False,
        'branch': branch,
        'base_sha': base_sha,
        'files': sorted(planned),
        'pull_request_url': pr.get('html_url'),
        'is_update': is_update,
    }
