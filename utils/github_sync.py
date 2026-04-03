import os
import base64
import requests
from pathlib import Path
from datetime import datetime
import config


GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "diegobarpereira/NBA_Stats")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

try:
    from config_local import GITHUB_TOKEN as LOCAL_TOKEN
    if LOCAL_TOKEN and not GITHUB_TOKEN:
        GITHUB_TOKEN = LOCAL_TOKEN
except ImportError:
    pass


def _get_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def push_file_to_github(content: bytes, file_path: str, commit_message: str = None) -> bool:
    if not GITHUB_TOKEN:
        return False
    
    if commit_message is None:
        commit_message = f"Add: {Path(file_path).name}"
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    
    try:
        existing = requests.get(url, headers=_get_headers())
        if existing.status_code == 200:
            sha = existing.json()["sha"]
        else:
            sha = None
        
        data = {
            "message": commit_message,
            "content": base64.b64encode(content).decode("utf-8"),
            "branch": GITHUB_BRANCH,
        }
        if sha:
            data["sha"] = sha
        
        response = requests.put(url, json=data, headers=_get_headers())
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"GitHub push error: {e}")
        return False


def push_bilhetes_to_github(bilhete_path: Path) -> bool:
    if not GITHUB_TOKEN:
        return False
    
    if not bilhete_path.exists():
        return False
    
    content = bilhete_path.read_bytes()
    relative_path = f"output/{bilhete_path.name}"
    
    return push_file_to_github(content, relative_path, f"Add: Bilhete {bilhete_path.stem}")


def push_comparison_data_to_github() -> bool:
    if not GITHUB_TOKEN:
        return False
    
    import json
    
    comparison_file = config.DATA_DIR / "comparison_history.json"
    if comparison_file.exists():
        content = comparison_file.read_bytes()
        push_file_to_github(content, "data/comparison_history.json", "Update: Comparison history")
    
    performance_file = config.DATA_DIR / "performance_history.json"
    if performance_file.exists():
        content = performance_file.read_bytes()
        push_file_to_github(content, "data/performance_history.json", "Update: Performance history")
    
    return True


def get_github_sync_status():
    return {
        "enabled": bool(GITHUB_TOKEN),
        "repo": GITHUB_REPO,
        "branch": GITHUB_BRANCH,
    }