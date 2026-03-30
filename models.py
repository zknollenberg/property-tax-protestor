"""
Pydantic data models for the property tax protest application.
All data originates from the CCAD Socrata API — nothing is fabricated.
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class PropertyInfo(BaseModel):
    """A single CCAD property record, exactly as returned from the API."""
    account_num: str
    owner_name: str = ""
    address: str
    city: str = ""
    zip_code: str = ""
    market_value: float          # Total CCAD appraised value
    land_value: float = 0.0
    improvement_value: float = 0.0
    bldg_sqft: Optional[float] = None
    yr_built: Optional[int] = None
    neighborhood_cd: str = ""    # CCAD neighborhood code used for comp selection
    state_class: str = ""        # State property class (A1/A2 = residential SF)
    data_year: str = ""          # Tax year this record reflects
    raw_data: Dict[str, Any] = {}


class ComparableProperty(BaseModel):
    """A comparable property from the same CCAD neighborhood."""
    account_num: str
    address: str
    market_value: float
    bldg_sqft: float
    yr_built: Optional[int] = None
    neighborhood_cd: str = ""
    value_per_sqft: float        # market_value / bldg_sqft


class ProtestReport(BaseModel):
    """Full analysis output — only populated when real comps are available."""
    subject: PropertyInfo
    comps: List[ComparableProperty] = []
    subject_value_per_sqft: Optional[float] = None
    median_comp_value_per_sqft: Optional[float] = None
    mean_comp_value_per_sqft: Optional[float] = None
    recommended_value: Optional[float] = None   # median $/sqft × subject sqft
    potential_reduction: Optional[float] = None
    # Tax savings are estimated using the user-supplied effective tax rate
    estimated_savings: Optional[float] = None
    protest_viable: bool = False
    protest_basis: str = ""      # "unequal_appraisal" or "insufficient_data"
    comps_count: int = 0
    data_source: str = "Collin CAD via Texas Open Data Portal (data.texas.gov)"


class LookupRequest(BaseModel):
    address: str


class AnalyzeRequest(BaseModel):
    account_num: str
    neighborhood_cd: str
    bldg_sqft: float
    yr_built: Optional[int] = None
    market_value: float
    effective_tax_rate: float = 1.8   # percent — user-provided from their tax bill


class FieldMap(BaseModel):
    """Discovered mapping from our canonical names → actual Socrata column names."""
    account_num: str = ""
    owner_name: str = ""
    situs_address: str = ""     # full address OR first component
    situs_num: str = ""
    situs_street: str = ""
    situs_city: str = ""
    situs_zip: str = ""
    market_value: str = ""
    land_value: str = ""
    improvement_value: str = ""
    bldg_sqft: str = ""
    yr_built: str = ""
    neighborhood_cd: str = ""
    state_class: str = ""
    data_year: str = ""
