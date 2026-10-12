"""
====================================================================================================
FASTAPI SERVER FOR TERRACED IRRIGATION (app.py)
Imports the core domain pipeline logic from pipeline.py.
Only responsible for HTTP routing, Pydantic validation, and JSON delivery.
====================================================================================================
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Import the standalone pipeline instance directly from pipeline.py
from pipeline import pipeline_instance

# --------------------------------------------------------------------------------------------------
# FASTAPI APP & CORS
# --------------------------------------------------------------------------------------------------
app = FastAPI(
    title="Terraced Precision Irrigation API",
    description="Elevation-Aware Soft-Sensor Irrigation Decision Engine for Terraced Hillside Farms (Ginger Crop)",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------------------------------
# SCHEMAS
# --------------------------------------------------------------------------------------------------
class Coordinates(BaseModel):
    grid_x: Optional[int] = Field(50, description="X index in the raster grid")
    grid_y: Optional[int] = Field(50, description="Y index in the raster grid")
    lat: Optional[float] = Field(None, description="Optional latitude coordinate")
    lon: Optional[float] = Field(None, description="Optional longitude coordinate")

class SensorPacket(BaseModel):
    sensor_id: str = Field(..., example="Ridge_Crest_Node")
    zone_id: Optional[str] = Field("Valve_A", example="Valve_A")
    raw_moisture: Optional[float] = Field(None, description="Raw analog ADC value (1880=dry, 1200=wet)", example=1690)
    raw_adc: Optional[float] = Field(None, description="Alternative key for raw ADC", example=1690)
    moisture: Optional[float] = Field(None, description="Optional pre-calibrated moisture [0.0 - 1.0]", example=0.28)
    temperature_c: Optional[float] = Field(25.0, description="Soil or ambient temperature in Celsius", example=26.5)
    temp_c: Optional[float] = Field(None, description="Alternative key for temperature in Celsius", example=26.5)
    coordinates: Optional[Coordinates] = Field(default_factory=Coordinates)
    timestamp: Optional[str] = Field(default_factory=lambda: datetime.utcnow().isoformat())

class IngestRequest(BaseModel):
    current_hour: Optional[float] = Field(13.0, ge=0.0, le=24.0, description="Time of day (0.0 to 24.0) for solar cycle")
    packets: List[SensorPacket] = Field(..., description="List of sensor telemetry packets from physical nodes")

class ZoneDecision(BaseModel):
    zone_name: str
    irrigation_need_score: float
    actuator_status: str
    current_min_moisture: float
    predicted_6h_moisture: float
    fao56_etc_mm_hr: float
    rain_probability_8h: float
    crop: str
    root_depth_m: float
    recommended_pulse_cycle: str

class PipelineResponse(BaseModel):
    status: str
    timestamp: str
    weather: Dict[str, Any]
    zones: Dict[str, ZoneDecision]

# --------------------------------------------------------------------------------------------------
# HTTP ENDPOINTS (CLEAN & MINIMAL)
# --------------------------------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "model_loaded": pipeline_instance.model is not None,
        "geotiff_loaded": pipeline_instance.tif_meta is not None
    }

@app.post("/api/predict_irrigation", response_model=PipelineResponse, tags=["Inference"])
def predict_irrigation(request: IngestRequest):
    """
    Main endpoint for frontend and electronics.
    Ingests sensor packets -> executes pipeline.py -> returns 0-1 scores.
    """
    if not request.packets:
        raise HTTPException(status_code=400, detail="No sensor packets provided.")

    # Convert Pydantic packets to raw dicts for the pipeline engine
    raw_list = [p.dict() for p in request.packets]
    hour = request.current_hour if request.current_hour is not None else 13.0

    try:
        results = pipeline_instance.run(raw_list, current_hour=hour)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/calibrate_sensor", tags=["Utilities"])
def calibrate_sensor(raw_adc: float = Query(..., description="Raw ADC count (e.g. 1650)")):
    """Converts raw analog ADC reading to calibrated moisture percentage."""
    normalized = pipeline_instance.calibrate_moisture_adc(raw_adc)
    return {
        "raw_adc": raw_adc,
        "calibrated_moisture_percentage": round(normalized * 100.0, 2),
        "calibrated_moisture_index": round(normalized, 4),
        "status": "Dry" if normalized < 0.30 else ("Optimal" if normalized < 0.60 else "Wet/Saturated")
    }

@app.get("/api/demo_payload", tags=["Utilities"])
def demo_payload():
    """Returns sample payload matching hardware packet schema."""
    return {
        "current_hour": 13.0,
        "packets": [
            {"sensor_id": "Ridge_Crest_Node", "zone_id": "Valve_A", "raw_moisture": 1690, "temperature_c": 26.8, "coordinates": {"grid_x": 90, "grid_y": 210}},
            {"sensor_id": "Mid_Slope_Node", "zone_id": "Valve_B", "raw_moisture": 1580, "temperature_c": 25.4, "coordinates": {"grid_x": 180, "grid_y": 126}},
            {"sensor_id": "Valley_Basin_Node", "zone_id": "Valve_C", "raw_moisture": 1440, "temperature_c": 23.9, "coordinates": {"grid_x": 270, "grid_y": 42}}
        ]
    }
