"""Shared app state with aggressive caching so pages render fast:
  * dataset, status, reviews and surveys are cached and cleared only when they change
  * ranking is cached per (agency, survey, data version)
  * heavy work (NOFO PDFs, AI explanations) is precomputed by the refresh job; the app only reads it,
    and computes on demand only when someone opens an item that was not precomputed."""
import json

import streamlit as st

from agency_profiles import loader
from common.ai import AI
from common.storage import Storage
from data_retrieval.store import freshness_label, load_dataset
from feedback import store as fb
from scoring.enrich import enrich_now, survey_key
from scoring.rank import rank
from summarization.explain import rule_explanation


@st.cache_resource
def storage() -> Storage:
    return Storage()


@st.cache_resource
def ai() -> AI:
    return AI()


@st.cache_data(ttl=60, show_spinner=False)
def status() -> dict:
    return storage().read_json("opportunities/status.json", default={}) or {}


@st.cache_data(ttl=600, show_spinner=False)
def dataset(version: str):
    return load_dataset(storage())


@st.cache_data(ttl=600, show_spinner=False)
def precomputed(agency_id: str, version: str) -> dict:
    return storage().read_json(f"precomputed/{agency_id}.json", default={}) or {}


@st.cache_data(ttl=120, show_spinner=False)
def reviews(agency_id: str) -> dict:
    return fb.reviews(storage(), agency_id)


@st.cache_data(ttl=300, show_spinner=False)
def saved_survey(agency_id: str):
    return fb.get_survey(storage(), agency_id)


def reviews_changed():
    reviews.clear()
    ranked.clear()


def survey_changed():
    saved_survey.clear()
    st.session_state.pop("enriched", None)


def data_changed():
    status.clear()
    dataset.clear()
    precomputed.clear()
    ranked.clear()
    st.session_state.pop("enriched", None)


def data_version(s: dict) -> str:
    return f"{s.get('mode')}|{s.get('last_success')}|{s.get('last_attempt')}"


def data_label(s: dict) -> str:
    return freshness_label(s)[1]


@st.cache_resource(show_spinner=False, max_entries=12)
def ranked(agency_id: str, survey_json: str, version: str, dismissed_json: str):
    items, _ = dataset(version)
    return rank(items, loader.get(agency_id), json.loads(survey_json), storage(), ai(), json.loads(dismissed_json))


def get_ranked(agency_id: str, survey: dict):
    s = status()
    rv = reviews(agency_id)
    dismissed = {k: {"action": "Pass"} for k, v in rv.items() if v["action"] == "Pass"}
    out = ranked(agency_id, json.dumps(survey, sort_keys=True, default=str), data_version(s),
                 json.dumps(dismissed, sort_keys=True))
    st.session_state.setdefault("_outs", {})[agency_id] = out
    out["_survey_key"] = survey_key(survey)
    out["_version"] = data_version(s)
    return out, rv


def current_out(agency_id: str):
    return st.session_state["_outs"][agency_id]


def _from_precomputed(result: dict, out: dict, agency_id: str) -> dict | None:
    pre = precomputed(agency_id, out.get("_version", ""))
    if not pre or pre.get("survey_key") != out.get("_survey_key") \
            or pre.get("data_success") != status().get("last_success"):
        return None
    item = (pre.get("items") or {}).get(result["record"]["id"])
    if not item:
        return None
    x = dict(item, record=result["record"], rank=result.get("rank"))
    x["other_targets"] = [tuple(t) for t in x.get("other_targets", [])]
    return x


def light(result: dict, out: dict, agency_id: str) -> dict:
    """Fast version for lists: precomputed enrichment if available, else rules explanation (no network)."""
    x = _from_precomputed(result, out, agency_id)
    if x:
        return x
    if "explanation" not in result:
        result["explanation"] = rule_explanation(result)
        result["confidence"] = result["explanation"]["confidence"]
        result["needs_review"] = result["confidence"] == "low"
    return result


basic = light  # backwards-compatible name


def enrich(result: dict, out: dict, agency_id: str) -> dict:
    """Full detail for one item: precomputed if available, else NOFO + AI explanation now (cached)."""
    x = _from_precomputed(result, out, agency_id)
    if x:
        return x
    cache = st.session_state.setdefault("enriched", {})
    key = (agency_id, result["record"]["id"], out.get("_survey_key"))
    if key in cache:
        return cache[key]
    with st.spinner("Reading the full notice and checking the evidence…"):
        x = enrich_now(result, out, agency_id, storage(), ai())
    cache[key] = x
    return x
