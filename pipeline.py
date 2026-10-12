"""
====================================================================================================
TERRACED PRECISION IRRIGATION PIPELINE (pipeline.py)
Core Domain Logic & ML Engine:
- Ingests GeoTIFF Topographic/Irrigation Index (D:\\Downloads\\irrigation_index.tif)
- Calibrates raw analog moisture sensor ADC counts (1880 in air -> 0.0, 1200 in water -> 1.0)
- Performs 3D RBF spatial interpolation across the terrain
- Evaluates FAO-56 Penman-Monteith crop evapotranspiration for Ginger (Kc = 1.10)
- Ingests pre-trained Random Forest model (rf_moisture_decay_model.pkl) for 6-8h decay prediction
- Fetches real-time 8h rain probability from Open-Meteo API
- Computes continuous Irrigation Need Score [0.0 - 1.0] for physical solenoid valves
====================================================================================================
"""

import os
import time
import requests
import joblib
import rasterio
import numpy as np
from scipy.interpolate import RBFInterpolator

# --------------------------------------------------------------------------------------------------
# CONFIGURATION & FILE PATHS
# --------------------------------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "rf_moisture_decay_model.pkl")
TIF_PATH = r"D:\Downloads\irrigation_index.tif"

ADC_AIR_DRY = 1880.0
ADC_WATER_WET = 1200.0

GINGER_KC = 1.10
GINGER_ROOT_DEPTH_M = 0.35
FIELD_CAPACITY = 0.55
STRESS_THRESHOLD = 0.34

class TerraceIrrigationPipeline:
    """Core pipeline class encapsulating geospatial data, ML model, and agronomic logic."""

    def __init__(self, tif_path: str = TIF_PATH, model_path: str = MODEL_PATH):
        self.tif_path = tif_path
        self.model_path = model_path
        self.model = None
        self.tif_meta = None
        self._load_assets()

    def _load_assets(self):
        """Loads the pre-trained Random Forest model and GeoTIFF raster into memory."""
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model file not found at: {self.model_path}")
        self.model = joblib.load(self.model_path)
        print(f"[Pipeline] Loaded Random Forest model: {self.model_path}")

        if not os.path.exists(self.tif_path):
            raise FileNotFoundError(f"GeoTIFF file not found at: {self.tif_path}")

        with rasterio.open(self.tif_path) as src:
            raw_data = src.read(1).astype(np.float32)
            transform = src.transform
            bounds = src.bounds
            crs = src.crs

        valid_mask = (raw_data > -1000.0) & (~np.isnan(raw_data))
        clean_data = np.where(valid_mask, raw_data, np.nan)
        median_val = np.nanmedian(clean_data)
        clean_data = np.nan_to_num(clean_data, nan=median_val)

        min_v, max_v = float(clean_data.min()), float(clean_data.max())
        norm_index = (clean_data - min_v) / (max_v - min_v + 1e-6)

        self.tif_meta = {
            "raw_grid": clean_data,
            "norm_grid": norm_index,
            "shape": clean_data.shape,
            "bounds": bounds,
            "transform": transform,
            "crs": str(crs),
            "min": min_v,
            "max": max_v
        }
        print(f"[Pipeline] Loaded GeoTIFF: Shape {self.tif_meta['shape']} | Range [{min_v:.2f}, {max_v:.2f}]")

    @staticmethod
    def calibrate_moisture_adc(raw_adc: float) -> float:
        """Converts raw analog ADC reading (1880 in air -> 0.0, 1200 in water -> 1.0) to [0.0, 1.0]."""
        moisture = (ADC_AIR_DRY - float(raw_adc)) / (ADC_AIR_DRY - ADC_WATER_WET)
        return float(np.clip(moisture, 0.0, 1.0))

    @staticmethod
    def calculate_fao56_etc(temp_c: float, hour_of_day: float = 13.0, rh_percent: float = 70.0) -> float:
        """FAO-56 Penman-Monteith Evapotranspiration for Ginger: ETc = Kc * ET0."""
        if 7.0 <= hour_of_day <= 19.0:
            solar_rad_w = 750.0 * np.sin(np.pi * (hour_of_day - 7.0) / 12.0)
        else:
            solar_rad_w = 0.0

        rn_mm_hr = (solar_rad_w * 0.0036) / 2.45
        sat_vp = 0.6108 * np.exp((17.27 * temp_c) / (temp_c + 237.3))
        act_vp = sat_vp * (rh_percent / 100.0)
        vpd = max(0.0, sat_vp - act_vp)

        et0_mm_hr = max(0.02, 0.408 * rn_mm_hr * 0.65 + 0.05 * vpd)
        etc_mm_hr = GINGER_KC * et0_mm_hr
        return float(etc_mm_hr)

    @staticmethod
    def fetch_weather_rain_forecast(lat: float = 27.14, lon: float = 88.30) -> dict:
        """Fetches 6-8 hour precipitation probability from Open-Meteo with fallback."""
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&hourly=precipitation_probability,precipitation"
            f"&forecast_days=2&timezone=Asia%2FKolkata"
        )
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                hourly_probs = data.get("hourly", {}).get("precipitation_probability", [])
                next_8h_prob = float(np.mean(hourly_probs[:8])) / 100.0
                return {
                    "status": "online",
                    "rain_prob_8h": float(np.clip(next_8h_prob, 0.0, 1.0)),
                    "source": "Open-Meteo API (South Sikkim)"
                }
        except Exception:
            pass

        return {
            "status": "simulated_offline",
            "rain_prob_8h": 0.15,
            "source": "Agronomic Weather Fallback"
        }

    def interpolate_moisture(self, parsed_packets: list) -> np.ndarray:
        """Interpolates 3D RBF spatial moisture grid across the terrain."""
        norm_grid = self.tif_meta["norm_grid"]
        h, w = norm_grid.shape

        sample_coords = []
        sample_values = []
        for p in parsed_packets:
            gx = min(max(0, p["grid_x"]), w - 1)
            gy = min(max(0, p["grid_y"]), h - 1)
            z_topo = float(norm_grid[gy, gx])
            sample_coords.append([gx / w, gy / h, z_topo])
            sample_values.append(p["moisture_norm"])

        sample_coords = np.array(sample_coords, dtype=np.float32)
        sample_values = np.array(sample_values, dtype=np.float32)

        stride_y = max(1, h // 60)
        stride_x = max(1, w // 60)
        sub_y, sub_x = np.mgrid[0:h:stride_y, 0:w:stride_x]
        sub_z = norm_grid[sub_y, sub_x]

        target_points = np.column_stack([
            (sub_x.ravel() / w),
            (sub_y.ravel() / h),
            sub_z.ravel()
        ])

        rbf = RBFInterpolator(sample_coords, sample_values, kernel='multiquadric', epsilon=0.8)
        sub_moisture = rbf(target_points).reshape(sub_y.shape)

        drainage_factor = 1.0 - 0.25 * (sub_z - np.mean(sub_z))
        sub_moisture = np.clip(sub_moisture * drainage_factor, 0.05, 0.95)
        return sub_moisture

    def run(self, raw_packets: list, current_hour: float = 13.0) -> dict:
        """
        Executes end-to-end pipeline:
        raw packets -> calibration -> 3D RBF -> FAO-56 -> Random Forest -> weather -> scores
        """
        parsed_list = []
        for pkt in raw_packets:
            if "raw_moisture" in pkt and pkt["raw_moisture"] is not None:
                calibrated_m = self.calibrate_moisture_adc(pkt["raw_moisture"])
            elif "raw_adc" in pkt and pkt["raw_adc"] is not None:
                calibrated_m = self.calibrate_moisture_adc(pkt["raw_adc"])
            elif "moisture" in pkt and pkt["moisture"] is not None:
                calibrated_m = float(np.clip(pkt["moisture"], 0.0, 1.0))
            else:
                calibrated_m = 0.35

            temp = pkt.get("temperature_c", pkt.get("temp_c", 25.0))
            coords = pkt.get("coordinates", {})
            gx = coords.get("grid_x", 50)
            gy = coords.get("grid_y", 50)

            parsed_list.append({
                "sensor_id": pkt.get("sensor_id", "Unknown_Sensor"),
                "zone_id": pkt.get("zone_id", "Valve_A"),
                "moisture_norm": calibrated_m,
                "temp_c": float(temp),
                "grid_x": int(gx),
                "grid_y": int(gy)
            })

        moist_grid = self.interpolate_moisture(parsed_list)
        h, w = moist_grid.shape

        weather = self.fetch_weather_rain_forecast()
        rain_prob = weather["rain_prob_8h"]

        zone_defs = {
            "Valve_A": {"name": "Upper Ridge Terrace", "rows": slice(int(h * 0.66), h), "idx": 0},
            "Valve_B": {"name": "Mid Terrace Bench", "rows": slice(int(h * 0.33), int(h * 0.66)), "idx": min(1, len(parsed_list)-1)},
            "Valve_C": {"name": "Lower Valley Basin", "rows": slice(0, int(h * 0.33)), "idx": min(2, len(parsed_list)-1)}
        }

        results = {}
        for z_id, z_data in zone_defs.items():
            z_moist = moist_grid[z_data["rows"], :]
            min_moisture = float(np.min(z_moist))
            sensor_ref = parsed_list[z_data["idx"]]
            temp_c = sensor_ref["temp_c"]

            etc = self.calculate_fao56_etc(temp_c, hour_of_day=current_hour)

            topo_val = 0.65 if z_id == "Valve_A" else (0.45 if z_id == "Valve_B" else 0.20)
            X_pred = np.array([[min_moisture, etc, topo_val, temp_c, 7.0]])
            pred_6h_moisture = float(self.model.predict(X_pred)[0])

            deficit_factor = max(0.0, (FIELD_CAPACITY - pred_6h_moisture) / (FIELD_CAPACITY - 0.15))
            rain_discount = max(0.0, 1.0 - (rain_prob * 1.5))
            raw_score = deficit_factor * rain_discount
            irrigation_score = float(np.clip(raw_score, 0.0, 1.0))

            if irrigation_score >= 0.65:
                status_text = "TRIGGER_IRRIGATION_HIGH"
                pulse_desc = "3 Bursts: 15 min ON / 20 min SOAK"
            elif irrigation_score >= 0.35:
                status_text = "MODERATE_IRRIGATION"
                pulse_desc = "2 Bursts: 10 min ON / 20 min SOAK"
            else:
                status_text = "STANDBY_OPTIMAL"
                pulse_desc = "No irrigation required (natural retention)"

            results[z_id] = {
                "zone_name": z_data["name"],
                "irrigation_need_score": round(irrigation_score, 3),
                "actuator_status": status_text,
                "current_min_moisture": round(min_moisture, 3),
                "predicted_6h_moisture": round(pred_6h_moisture, 3),
                "fao56_etc_mm_hr": round(etc, 3),
                "rain_probability_8h": round(rain_prob, 2),
                "crop": "Ginger (Kc=1.10)",
                "root_depth_m": GINGER_ROOT_DEPTH_M,
                "recommended_pulse_cycle": pulse_desc
            }

        return {
            "status": "success",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "weather": weather,
            "zones": results
        }


# Singleton pipeline instance ready for imports
pipeline_instance = TerraceIrrigationPipeline()

if __name__ == "__main__":
    print("=" * 80)
    print("RUNNING TERRACE IRRIGATION PIPELINE STANDALONE")
    print("=" * 80)

    sample_packets = [
        {"sensor_id": "Ridge_Crest_Node", "zone_id": "Valve_A", "raw_moisture": 1690, "temperature_c": 26.8, "coordinates": {"grid_x": 90, "grid_y": 210}},
        {"sensor_id": "Mid_Slope_Node", "zone_id": "Valve_B", "raw_moisture": 1580, "temperature_c": 25.4, "coordinates": {"grid_x": 180, "grid_y": 126}},
        {"sensor_id": "Valley_Basin_Node", "zone_id": "Valve_C", "raw_moisture": 1440, "temperature_c": 23.9, "coordinates": {"grid_x": 270, "grid_y": 42}}
    ]

    output = pipeline_instance.run(sample_packets, current_hour=13.0)
    print("Weather:", output["weather"])
    for v_id, z in output["zones"].items():
        print(f"[{v_id}] {z['zone_name']} -> Score: {z['irrigation_need_score']} | Status: {z['actuator_status']}")
