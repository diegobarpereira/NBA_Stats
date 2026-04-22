import json
import os
import requests
from pathlib import Path
from datetime import datetime
import config

GITHUB_RAW_URL = "https://raw.githubusercontent.com/diegobarpereira/NBA_Stats/main/data/cache_stats.json"
CACHE_FILE = config.DATA_DIR / "cache_stats.json"
MAX_CACHE_AGE_HOURS = 24


def sync_cache_from_github(force: bool = False) -> bool:
    """
    Tenta sincronizar o cache do GitHub.
    Retorna True se sincronizou com sucesso.
    """
    # Verifica se está no Streamlit Cloud
    is_cloud = os.environ.get("STREAMLIT_SHARING_MODE") is not None or os.environ.get("STREAMLIT_CLOUD"]) is not None
    
    if not is_cloud and not force:
        print("Ambiente local - usando cache local")
        return False
    
    # Verifica se precisa atualizar
    if CACHE_FILE.exists() and not force:
        try:
            with open(CACHE_FILE, "r") as f:
                local_cache = json.load(f)
            
            # Verifica idade do cache
            sample_player = list(local_cache.keys())[0] if local_cache else None
            if sample_player:
                last_update = local_cache[sample_player].get("last_updated", "")
                if last_update:
                    try:
                        update_date = datetime.fromisoformat(last_update)
                        age = (datetime.now() - update_date).total_seconds() / 3600
                        if age < MAX_CACHE_AGE_HOURS:
                            print(f"Cache local recente ({age:.1f}h) - usando local")
                            return False
                    except:
                        pass
        except:
            pass
    
    # Tenta baixar do GitHub
    print("Tentando sincronizar cache do GitHub...")
    try:
        response = requests.get(GITHUB_RAW_URL, timeout=30)
        if response.status_code == 200:
            github_cache = response.json()
            
            # Salva localmente
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(github_cache, f, ensure_ascii=False, indent=2)
            
            print(f"Cache sincronizado do GitHub: {len(github_cache)} jogadores")
            return True
        else:
            print(f"GitHub returned {response.status_code}")
    except Exception as e:
        print(f"Erro ao sincronizar cache: {e}")
    
    return False


def save_and_push_cache() -> bool:
    """
    Salva o cache local e exibe instruções para push.
    """
    print("\n" + "="*60)
    print("Para sincronizar com Cloud, execute:")
    print("  git add data/cache_stats.json")
    print("  git commit -m 'Atualiza cache'")
    print("  git push")
    print("="*60 + "\n")


if __name__ == "__main__":
    # Teste de sync
    synced = sync_cache_from_github(force=True)
    print(f"Sincronizado: {synced}")
