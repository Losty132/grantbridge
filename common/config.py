"""All configuration comes from environment variables (see .env.example). No secrets in code."""
import os

try:  # local development: load .env (VS Code launch configs also read it). On Azure, real env vars are used.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _secret(name: str) -> str:
    v = os.getenv(name, "").strip()
    return "" if v.lower() in ("", "none", "null") else v


# Storage: Azure Blob if STORAGE_CONN is set, otherwise a local folder (persistent volume on Azure).
STORAGE_CONN = _secret("STORAGE_CONN")
STORAGE_CONTAINER = os.getenv("STORAGE_CONTAINER", "ffm-data")
LOCAL_DATA_DIR = os.getenv("LOCAL_DATA_DIR", "./data")

# Azure OpenAI (optional; every feature has a non-AI fallback)
AOAI_ENDPOINT = _secret("AOAI_ENDPOINT")
AOAI_KEY = _secret("AOAI_KEY")
AOAI_API_VERSION = os.getenv("AOAI_API_VERSION", "2024-10-21")
AOAI_CHAT_DEPLOYMENT = os.getenv("AOAI_CHAT_DEPLOYMENT", "chat")
AOAI_EMBED_DEPLOYMENT = os.getenv("AOAI_EMBED_DEPLOYMENT", "embed")
EMBED_DIMENSIONS = _int("EMBED_DIMENSIONS", 256)

# Azure AI Language PII detection (optional privacy layer 1)
LANGUAGE_ENDPOINT = _secret("LANGUAGE_ENDPOINT")
LANGUAGE_KEY = _secret("LANGUAGE_KEY")

# Ingestion
BROAD_ELIGIBILITIES = [c.strip() for c in os.getenv("BROAD_ELIGIBILITIES", "00,25,99").split(",") if c.strip()]
BROAD_PULL_CAP = _int("BROAD_PULL_CAP", 1000)
KEYWORD_PULL_CAP = _int("KEYWORD_PULL_CAP", 150)
DETAIL_FETCH_CAP = _int("DETAIL_FETCH_CAP", 2500)
DETAIL_MAX_AGE_DAYS = _int("DETAIL_MAX_AGE_DAYS", 7)   # re-fetch details at least weekly to catch amendments
FETCH_WORKERS = _int("FETCH_WORKERS", 8)
NOFO_FETCH = os.getenv("NOFO_FETCH", "1") == "1"   # download + parse NOFO PDFs for top results

# Agencies offered in the survey (profiles in agency_profiles/profiles/)
# Which agency profiles to show. "all" (default) = every profile in agency_profiles/profiles/; or a comma list.
_AG = os.getenv("AGENCIES", "all").strip().lower()
AGENCIES = None if _AG in ("", "all", "*") else [a.strip() for a in _AG.split(",") if a.strip()]

