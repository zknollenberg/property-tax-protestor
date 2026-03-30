"""
Collin CAD data client.

Primary source: Texas Open Data Portal Socrata API
  Dataset: Collin CAD Appraisal Database
  Endpoint: https://data.texas.gov/resource/7ugx-vxwc.json
  Docs: https://dev.socrata.com/foundry/data.texas.gov/7ugx-vxwc

The client auto-discovers the actual column names on first use so it stays
correct even if CCAD publishes a new dataset with slightly different headers.

Set SOCRATA_APP_TOKEN in .env for higher rate limits (free at data.texas.gov).
"""

import os
import re
import logging
from typing import Optional

import httpx

from models import FieldMap, PropertyInfo

logger = logging.getLogger(__name__)

# ── Socrata endpoints ──────────────────────────────────────────────────────────
SOCRATA_BASE = "https://data.texas.gov/resource"

# Ordered by recency. The client tries each until one returns data.
DATASET_IDS = [
    ("7ugx-vxwc", "current"),   # Current / most recent CCAD upload
    ("khef-anha", "2023"),
    ("vtby-uz4n", "2022"),
]

# ── Candidate column names for each logical field ─────────────────────────────
# Lists are in preference order; first match wins.
CANDIDATES: dict[str, list[str]] = {
    "account_num":        ["account_num", "prop_id", "account_number", "geo_id", "id"],
    "owner_name":         ["owner_name", "owner", "dba_name", "owner_1"],
    "situs_address":      ["situs_addr", "situs_addr_1", "site_addr_1",
                           "site_addr", "street_address", "address"],
    "situs_num":          ["situs_num", "situs_street_num", "house_num", "str_num"],
    "situs_street":       ["situs_street_name", "situs_street", "street_name", "str_name"],
    "situs_city":         ["situs_city", "city", "site_city"],
    "situs_zip":          ["situs_zip", "zip", "site_zip", "zip_code"],
    "market_value":       ["market_value", "appraised_value", "total_value",
                           "assessed_value", "mrkt_val", "tot_mkt_val"],
    "land_value":         ["land_value", "land_val", "land_hstd_val"],
    "improvement_value":  ["improvement_value", "imprv_value", "imprv_val",
                           "bldg_val", "improvement_val"],
    "bldg_sqft":          ["bldg_area", "living_area", "sqft", "sq_ft",
                           "building_area", "bldg_sqft", "living_sqft",
                           "heated_area", "total_area"],
    "yr_built":           ["yr_built", "year_built", "act_yr_blt",
                           "actual_yr_blt", "eff_yr_blt"],
    "neighborhood_cd":    ["neighborhood_cd", "nbhd_cd", "neighborhood_code",
                           "hood_cd", "nbhd"],
    "state_class":        ["state_class", "state_cd", "state_class_cd",
                           "property_type", "prop_type_cd"],
    "data_year":          ["tax_yr", "year", "appraisal_yr", "prop_yr"],
}

# Residential state-class codes (single-family)
RESIDENTIAL_CLASSES = {"A1", "A2", "A3", "A4", "RES", "RESIDENTIAL"}


class CCadClient:
    """Async client for the Collin CAD Socrata dataset."""

    def __init__(self):
        token = os.getenv("SOCRATA_APP_TOKEN", "")
        headers = {"Accept": "application/json"}
        if token:
            headers["X-App-Token"] = token
        self._http = httpx.AsyncClient(headers=headers, timeout=30.0)
        self._dataset_id: str = DATASET_IDS[0][0]
        self._data_year: str = DATASET_IDS[0][1]
        self._field_map: Optional[FieldMap] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def search_by_address(self, raw_address: str) -> list[dict]:
        """
        Search CCAD for a property matching the given address string.
        Returns a list of raw Socrata records (may be >1 if street number
        matches multiple units).  Raises on HTTP / parse errors.
        """
        await self._ensure_field_map()
        fm = self._field_map

        parts = _parse_address(raw_address)
        street_num = parts.get("number", "")
        street_name = parts.get("street_name", "")

        # Build a WHERE clause with what we have.
        # Strategy A: separate num + name columns
        # Strategy B: single combined address column
        clauses = []

        if fm.situs_num and fm.situs_street and street_num and street_name:
            clauses.append(
                f"upper({fm.situs_num})='{street_num}' "
                f"AND upper({fm.situs_street}) LIKE '%{street_name}%'"
            )

        if fm.situs_address:
            # Full-text LIKE on a single address field
            probe = f"{street_num} {street_name}".strip()
            if probe:
                clauses.append(f"upper({fm.situs_address}) LIKE '%{probe}%'")

        results = []
        for clause in clauses:
            rows = await self._query({"$where": clause, "$limit": "10"})
            if rows:
                results = rows
                break

        return results

    async def get_comparables(
        self,
        neighborhood_cd: str,
        bldg_sqft: float,
        yr_built: Optional[int],
        limit: int = 200,
    ) -> list[dict]:
        """
        Return up to `limit` residential properties in the same CCAD
        neighborhood with similar size and age.  Only returns real records.
        """
        await self._ensure_field_map()
        fm = self._field_map

        if not fm.neighborhood_cd or not fm.bldg_sqft:
            raise RuntimeError(
                "Cannot find comparable properties: neighborhood or sqft "
                "columns were not detected in the CCAD dataset. "
                "Run /api/schema to see available columns."
            )

        sqft_lo = round(bldg_sqft * 0.75)
        sqft_hi = round(bldg_sqft * 1.25)

        where_parts = [
            f"{fm.neighborhood_cd}='{neighborhood_cd}'",
            f"{fm.bldg_sqft} BETWEEN {sqft_lo} AND {sqft_hi}",
            f"{fm.bldg_sqft} > 0",
            f"{fm.market_value} > 0",
        ]

        if yr_built and fm.yr_built:
            yr_lo = yr_built - 15
            yr_hi = yr_built + 15
            where_parts.append(f"{fm.yr_built} BETWEEN {yr_lo} AND {yr_hi}")

        if fm.state_class:
            res_list = ", ".join(f"'{c}'" for c in RESIDENTIAL_CLASSES)
            where_parts.append(f"upper({fm.state_class}) IN ({res_list})")

        where = " AND ".join(where_parts)
        return await self._query(
            {"$where": where, "$limit": str(limit), "$order": f"{fm.bldg_sqft} ASC"}
        )

    async def get_schema(self) -> dict:
        """Return one raw record so callers can see available column names."""
        await self._ensure_field_map()
        sample = await self._query({"$limit": "1"})
        return {
            "dataset_id": self._dataset_id,
            "data_year": self._data_year,
            "field_map": self._field_map.model_dump(),
            "sample_record": sample[0] if sample else {},
        }

    def map_to_property(self, raw: dict) -> PropertyInfo:
        """Convert a raw Socrata record to a typed PropertyInfo."""
        fm = self._field_map

        def get(field_name: str, default="") -> str:
            col = getattr(fm, field_name, "")
            return str(raw.get(col, default)).strip() if col else default

        def get_float(field_name: str) -> float:
            col = getattr(fm, field_name, "")
            val = raw.get(col, 0) if col else 0
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        def get_int(field_name: str) -> Optional[int]:
            col = getattr(fm, field_name, "")
            val = raw.get(col) if col else None
            if val is None:
                return None
            try:
                return int(float(val))
            except (TypeError, ValueError):
                return None

        # Build address string from components or single field
        address_parts = []
        if fm.situs_num:
            n = str(raw.get(fm.situs_num, "")).strip()
            if n:
                address_parts.append(n)
        if fm.situs_street:
            s = str(raw.get(fm.situs_street, "")).strip()
            if s:
                address_parts.append(s)

        if address_parts:
            address = " ".join(address_parts)
        else:
            address = get("situs_address")

        return PropertyInfo(
            account_num=get("account_num") or "UNKNOWN",
            owner_name=get("owner_name"),
            address=address,
            city=get("situs_city"),
            zip_code=get("situs_zip"),
            market_value=get_float("market_value"),
            land_value=get_float("land_value"),
            improvement_value=get_float("improvement_value"),
            bldg_sqft=get_float("bldg_sqft") or None,
            yr_built=get_int("yr_built"),
            neighborhood_cd=get("neighborhood_cd"),
            state_class=get("state_class"),
            data_year=self._data_year,
            raw_data=raw,
        )

    # ── Internals ──────────────────────────────────────────────────────────────

    async def _query(self, params: dict) -> list[dict]:
        """Execute a Socrata SoQL GET query; try each dataset in order."""
        last_exc: Exception = RuntimeError("No datasets tried")
        for ds_id, ds_year in DATASET_IDS:
            url = f"{SOCRATA_BASE}/{ds_id}.json"
            try:
                resp = await self._http.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if data:
                    self._dataset_id = ds_id
                    self._data_year = ds_year
                    return data
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                logger.warning("Socrata %s returned %s", ds_id, exc.response.status_code)
            except Exception as exc:
                last_exc = exc
                logger.warning("Socrata %s error: %s", ds_id, exc)
        raise RuntimeError(
            f"Could not reach the CCAD dataset on data.texas.gov. "
            f"Last error: {last_exc}. "
            "Check your internet connection or try again later. "
            "The app never fabricates property data."
        )

    async def _ensure_field_map(self):
        if self._field_map is not None:
            return
        sample = await self._query({"$limit": "1"})
        if not sample:
            raise RuntimeError(
                "CCAD dataset returned no records. "
                "The dataset may be temporarily unavailable."
            )
        self._field_map = _discover_fields(sample[0])
        logger.info("Discovered field map: %s", self._field_map.model_dump())


def _discover_fields(record: dict) -> FieldMap:
    """
    Map our canonical field names to whatever column names exist in `record`.
    Matching is case-insensitive.
    """
    available = {k.lower(): k for k in record.keys()}
    mapping: dict[str, str] = {}
    for logical, candidates in CANDIDATES.items():
        for cand in candidates:
            if cand.lower() in available:
                mapping[logical] = available[cand.lower()]
                break
    return FieldMap(**mapping)


def _parse_address(raw: str) -> dict[str, str]:
    """
    Extract house number and street name from a free-text address string.
    Returns {"number": "1234", "street_name": "MAIN"} or empty strings.

    Deliberately simple — the Socrata LIKE filter handles the rest.
    """
    raw = raw.strip()
    # Remove city/state/zip suffix: "..., Frisco, TX 75034"
    raw_clean = re.split(r",\s*[A-Za-z ]+,\s*TX", raw, flags=re.IGNORECASE)[0]
    raw_clean = re.sub(r"\s+TX\s+\d{5}", "", raw_clean, flags=re.IGNORECASE)
    raw_clean = re.sub(r"\s+\d{5}$", "", raw_clean).strip()

    # House number is the leading digits (may include a letter suffix, e.g. 123A)
    num_match = re.match(r"^(\d+[A-Za-z]?)\s+(.*)", raw_clean)
    if not num_match:
        return {"number": "", "street_name": raw_clean.upper()}

    number = num_match.group(1)
    street_tail = num_match.group(2)

    # Strip direction prefix (N, S, E, W, NE, …)
    street_tail = re.sub(r"^(N|S|E|W|NE|NW|SE|SW)\s+", "", street_tail, flags=re.IGNORECASE)

    # Keep only the first "word" tokens — stop before suffix (St, Ave, Dr, …)
    SUFFIXES = {
        "ST", "AVE", "DR", "BLVD", "LN", "CT", "WAY", "RD", "PKWY",
        "FWY", "HWY", "CIR", "PL", "TRL", "TER", "STREET", "AVENUE",
        "DRIVE", "BOULEVARD", "LANE", "COURT", "ROAD", "PARKWAY",
        "FREEWAY", "HIGHWAY", "CIRCLE", "PLACE", "TRAIL", "TERRACE",
        "PASS", "PATH", "RUN", "XING", "PT",
    }
    words = street_tail.split()
    name_words = []
    for w in words:
        if w.upper() in SUFFIXES:
            break
        name_words.append(w.upper())

    return {"number": number, "street_name": " ".join(name_words)}
