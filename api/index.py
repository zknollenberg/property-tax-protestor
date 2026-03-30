"""
Vercel entry point for the Property Tax Protest app.

Vercel's @vercel/python builder picks up api/index.py and exposes `app`.
All root-level helper modules (models, ccad_client, protest_engine) and the
templates/ directory are bundled via includeFiles in vercel.json.

Local dev: uvicorn api.index:app --reload  (or via app.py re-export)
"""

import logging
import sys
from pathlib import Path

# Make root-level modules importable whether running locally or on Vercel.
# On Vercel: __file__ = /var/task/api/index.py → parent.parent = /var/task/
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

# Root-level modules bundled via vercel.json includeFiles
from ccad_client import CCadClient
from models import AnalyzeRequest, LookupRequest
from protest_engine import build_report, format_protest_letter

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Lazy client (serverless-safe: no lifespan hook) ───────────────────────────

_client: CCadClient | None = None


def get_client() -> CCadClient:
    global _client
    if _client is None:
        _client = CCadClient()
    return _client


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Collin County Property Tax Protest",
    description=(
        "Looks up your property on the Collin Central Appraisal District "
        "dataset (data.texas.gov) and builds an unequal-appraisal protest "
        "package using only real CCAD data."
    ),
)

# Templates live at <project_root>/templates/ — bundled by vercel.json includeFiles.
# Using an absolute path works in both local and serverless environments.
templates = Jinja2Templates(directory=str(_ROOT / "templates"))


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── API ───────────────────────────────────────────────────────────────────────

@app.post("/api/lookup")
async def lookup_property(req: LookupRequest):
    """
    Look up a Collin County residential property by street address.
    Returns the raw CCAD record(s) from data.texas.gov.
    Raises 404 if nothing is found — never returns invented data.
    """
    if not req.address.strip():
        raise HTTPException(status_code=400, detail="Address is required.")

    client = get_client()
    try:
        rows = await client.search_by_address(req.address)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No property found matching '{req.address}' in the CCAD "
                "dataset. Check the spelling or try the full street name. "
                "The CCAD dataset on data.texas.gov may lag the current "
                "appraisal year by one cycle — if your property was newly "
                "built, it may not yet be listed."
            ),
        )

    properties = [client.map_to_property(r) for r in rows]
    return {
        "matches": [p.model_dump() for p in properties],
        "raw_records": rows,
        "data_source": (
            f"Collin CAD Appraisal Database — Texas Open Data Portal "
            f"(data.texas.gov, dataset {client._dataset_id}, "
            f"tax year {client._data_year})"
        ),
    }


@app.post("/api/analyze")
async def analyze_property(req: AnalyzeRequest):
    """
    Find comparable properties in the same CCAD neighborhood and build
    a Texas Tax Code §41.43 unequal-appraisal protest report.
    """
    if not req.neighborhood_cd:
        raise HTTPException(
            status_code=400,
            detail=(
                "No neighborhood code found for this property. "
                "Without a CCAD neighborhood code, comparable properties "
                "cannot be selected objectively."
            ),
        )
    if not req.bldg_sqft or req.bldg_sqft <= 0:
        raise HTTPException(
            status_code=400,
            detail="Building square footage is required for the analysis.",
        )

    client = get_client()
    try:
        raw_comps = await client.get_comparables(
            neighborhood_cd=req.neighborhood_cd,
            bldg_sqft=req.bldg_sqft,
            yr_built=req.yr_built,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    from models import PropertyInfo
    subject = PropertyInfo(
        account_num=req.account_num,
        address="(subject)",
        market_value=req.market_value,
        bldg_sqft=req.bldg_sqft,
        yr_built=req.yr_built,
        neighborhood_cd=req.neighborhood_cd,
    )

    report = build_report(
        subject=subject,
        raw_comps=raw_comps,
        effective_tax_rate_pct=req.effective_tax_rate,
        client=client,
    )

    return {
        "report": report.model_dump(),
        "data_source": (
            f"Collin CAD Appraisal Database — Texas Open Data Portal "
            f"(data.texas.gov, dataset {client._dataset_id}, "
            f"tax year {client._data_year})"
        ),
    }


@app.post("/api/letter")
async def generate_letter(payload: dict):
    """Generate a plain-text protest letter from a previously computed report."""
    from models import ComparableProperty, PropertyInfo, ProtestReport
    try:
        report_data = payload.get("report", {})
        contact     = payload.get("contact", {})

        subject = PropertyInfo(**report_data["subject"])
        comps   = [ComparableProperty(**c) for c in report_data.get("comps", [])]
        report  = ProtestReport(
            subject=subject,
            comps=comps,
            **{k: v for k, v in report_data.items()
               if k not in ("subject", "comps")}
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid report data: {exc}")

    letter = format_protest_letter(report, contact)
    return PlainTextResponse(letter)


@app.get("/api/schema")
async def get_schema():
    """Return one raw CCAD record and the auto-discovered field map (debug)."""
    try:
        return await get_client().get_schema()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/healthz")
async def health():
    return {"status": "ok"}
