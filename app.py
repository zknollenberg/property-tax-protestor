"""
Property Tax Protest — Collin County, TX  (demo)

Run:
    pip install -r requirements.txt
    uvicorn app:app --reload

Then open http://localhost:8000
"""

import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from models import LookupRequest, AnalyzeRequest
from ccad_client import CCadClient
from protest_engine import build_report, format_protest_letter

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Application state ─────────────────────────────────────────────────────────

_client: CCadClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = CCadClient()
    yield
    await _client._http.aclose()


app = FastAPI(
    title="Collin County Property Tax Protest",
    description=(
        "Looks up your property on the Collin Central Appraisal District "
        "dataset (data.texas.gov) and builds an unequal-appraisal protest "
        "package using only real CCAD data."
    ),
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── API ───────────────────────────────────────────────────────────────────────

@app.post("/api/lookup")
async def lookup_property(req: LookupRequest):
    """
    Look up a Collin County residential property by street address.

    Returns the raw CCAD record(s) from data.texas.gov plus a typed
    PropertyInfo object.  Raises 404 if nothing is found — never returns
    invented data.
    """
    if not req.address.strip():
        raise HTTPException(status_code=400, detail="Address is required.")

    try:
        rows = await _client.search_by_address(req.address)
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

    # Return all matches so the UI can let the user pick the right one
    properties = [_client.map_to_property(r) for r in rows]
    return {
        "matches": [p.model_dump() for p in properties],
        "raw_records": rows,
        "data_source": (
            f"Collin CAD Appraisal Database — Texas Open Data Portal "
            f"(data.texas.gov, dataset {_client._dataset_id}, "
            f"tax year {_client._data_year})"
        ),
    }


@app.post("/api/analyze")
async def analyze_property(req: AnalyzeRequest):
    """
    Find comparable properties in the same CCAD neighborhood and build
    a protest report.

    `account_num` is used to exclude the subject from the comps list.
    `effective_tax_rate` should come from the owner's actual Collin County
    tax bill (City + ISD + County + MUD rates combined).
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

    try:
        raw_comps = await _client.get_comparables(
            neighborhood_cd=req.neighborhood_cd,
            bldg_sqft=req.bldg_sqft,
            yr_built=req.yr_built,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # Reconstruct a minimal PropertyInfo for the subject from the request
    # (the full record was already returned by /api/lookup)
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
        client=_client,
    )

    return {
        "report": report.model_dump(),
        "data_source": (
            f"Collin CAD Appraisal Database — Texas Open Data Portal "
            f"(data.texas.gov, dataset {_client._dataset_id}, "
            f"tax year {_client._data_year})"
        ),
    }


@app.post("/api/letter")
async def generate_letter(payload: dict):
    """
    Generate a plain-text protest letter from a previously computed report.
    The caller passes the full report JSON plus optional owner contact info.
    """
    from models import ProtestReport, PropertyInfo, ComparableProperty
    try:
        report_data = payload.get("report", {})
        contact     = payload.get("contact", {})

        # Rebuild typed objects
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
    """
    Return one raw CCAD record and the auto-discovered field map.
    Useful for debugging field-name issues with a new dataset.
    """
    try:
        return await _client.get_schema()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/healthz")
async def health():
    return {"status": "ok"}
