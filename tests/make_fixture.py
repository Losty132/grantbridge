"""Builds tests/fixtures/TEST_ONLY_raw.json: SYNTHETIC records for automated tests only (titles start with
[TEST ONLY]). The app never ships or displays this data; real runs use live Grants.gov data."""
import json
from datetime import date, timedelta
from pathlib import Path

T = date.today()
def d(n): return (T + timedelta(days=n)).strftime("%m/%d/%Y")
ROWS = [
 # id, title, agency code, agency name, status, days, description, elig, ceiling, cost share
 ("9001", "[TEST ONLY] Drinking water PFAS reduction", "EPA", "Environmental Protection Agency", "posted", 60,
  "Supports states to reduce PFAS in drinking water systems. Applicants must describe and justify all proposed costs in a budget justification. The project narrative may not exceed 20 pages. Two letters of support are required.",
  ["00"], "2000000", "false"),
 ("9002", "[TEST ONLY] Coastal resilience planning", "DOC-NOAA-ERA", "National Oceanic and Atmospheric Administration", "posted", 10,
  "Funds coastal resilience and flood hazard mitigation planning for states. A 25 percent non-federal match is required.",
  ["00"], "750000", "true"),
 ("9003", "[TEST ONLY] University geologic mapping training", "DOI-USGS1", "Geological Survey", "posted", 40,
  "Supports universities to train students in geologic mapping of landslide hazards. Only institutions of higher education may apply.",
  ["06"], "180000", "true"),
 ("9004", "[TEST ONLY] Small business agriculture innovation", "USDA", "Department of Agriculture", "posted", 45,
  "Supports small businesses developing prototypes.", ["23"], "150000", "false"),
 ("9005", "[TEST ONLY] Expired water grant", "EPA", "Environmental Protection Agency", "posted", -2,
  "Water quality monitoring for states.", ["00"], "100000", "false"),
 ("9006", "[TEST ONLY] Library digitization", "IMLS", "Institute of Museum and Library Services", "forecasted", None,
  "Supports state library agencies to digitize archives and historic collections.", ["00"], "500000", "false"),
 ("9007", "[TEST ONLY] Tiny planning award", "EPA", "Environmental Protection Agency", "posted", 50,
  "Supports watershed planning for water quality.", ["00"], "20000", "false"),
 ("9008", "[TEST ONLY] Others-eligibility hazard grant", "FEMA", "Department of Homeland Security - FEMA", "posted", 90,
  "Supports hazard mitigation for natural hazards and extreme weather.", ["25"], "1000000", ""),
]
hits, details = [], {}
for oid, title, code, name, status, days, desc, elig, ceil, cs in ROWS:
    hits.append({"id": oid, "number": f"TEST-{oid}", "title": title, "agencyCode": code, "agencyName": name,
                 "openDate": d(-10), "closeDate": d(days) if days is not None else "", "oppStatus": status,
                 "docType": "synopsis", "alnist": [], "found_by": ["broad"]})
    block = {"awardCeiling": ceil, "costSharing": cs, "applicantTypes": [{"id": e, "description": ""} for e in elig]}
    if status == "forecasted":
        details[oid] = {"id": oid, "opportunityNumber": f"TEST-{oid}", "opportunityTitle": title, "synopsis": {},
                        "forecast": dict(block, forecastDesc=desc, estApplicationResponseDate=d(120)), "attachments": []}
    else:
        details[oid] = {"id": oid, "opportunityNumber": f"TEST-{oid}", "opportunityTitle": title,
                        "synopsis": dict(block, synopsisDesc=desc), "forecast": {}, "attachments": []}
Path(__file__).parent.joinpath("fixtures/TEST_ONLY_raw.json").write_text(json.dumps(
    {"source": "TEST ONLY synthetic records", "pulled_at": T.isoformat() + "T10:00:00+00:00", "hits": hits,
     "details": details}, indent=1))
print(len(hits), "synthetic records")
