# Terraced Precision Irrigation REST API Documentation

High-performance production REST API for the **Elevation-Aware Soft-Sensor Irrigation System** (Ginger Crop, South Sikkim).

---

## 🚀 How to Run the Server

From the project directory:
```powershell
cd D:\coding\projects\terrace_irrigation_pipeline
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```
Once running, open the interactive Swagger UI:
👉 **`http://localhost:8000/docs`**

---

## 📡 API Endpoints

### 1. `POST /api/predict_irrigation` (Main Pipeline Endpoint)
Ingests live or simulated sensor telemetry packets, runs 3D RBF spatial interpolation on `irrigation_index.tif`, applies FAO-56 Penman-Monteith crop physics, calls the saved Random Forest model (`rf_moisture_decay_model.pkl`), queries live rain probabilities, and outputs the decision score for each solenoid valve.

#### Request Body (`application/json`):
```json
{
  "current_hour": 13.0,
  "packets": [
    {
      "sensor_id": "Ridge_Crest_Node",
      "zone_id": "Valve_A",
      "raw_moisture": 1690,
      "temperature_c": 26.8,
      "coordinates": {
        "grid_x": 90,
        "grid_y": 210
      }
    },
    {
      "sensor_id": "Mid_Slope_Node",
      "zone_id": "Valve_B",
      "raw_moisture": 1580,
      "temperature_c": 25.4,
      "coordinates": {
        "grid_x": 180,
        "grid_y": 126
      }
    },
    {
      "sensor_id": "Valley_Basin_Node",
      "zone_id": "Valve_C",
      "raw_moisture": 1440,
      "temperature_c": 23.9,
      "coordinates": {
        "grid_x": 270,
        "grid_y": 42
      }
    }
  ]
}
```

*Note: The hardware ADC conversion uses:*
$$\text{Moisture} = \text{clip}\left(\frac{1880 - \text{raw\_moisture}}{1880 - 1200}, 0.0, 1.0\right)$$
*(1880 in air = 0.0, 1200 submerged in water = 1.0)*

#### Response Body (`200 OK`):
```json
{
  "status": "success",
  "timestamp": "2026-10-12T16:04:00.123456",
  "weather": {
    "status": "online",
    "rain_prob_8h": 0.12,
    "source": "Open-Meteo API (South Sikkim)"
  },
  "zones": {
    "Valve_A": {
      "zone_name": "Upper Ridge Terrace",
      "irrigation_need_score": 0.922,
      "actuator_status": "TRIGGER_IRRIGATION_HIGH",
      "current_min_moisture": 0.21,
      "predicted_6h_moisture": 0.041,
      "fao56_etc_mm_hr": 0.38,
      "rain_probability_8h": 0.12,
      "crop": "Ginger (Kc=1.10)",
      "root_depth_m": 0.35,
      "recommended_pulse_cycle": "3 Bursts: 15 min ON / 20 min SOAK"
    },
    "Valve_B": {
      "zone_name": "Mid Terrace Bench",
      "irrigation_need_score": 0.821,
      "actuator_status": "TRIGGER_IRRIGATION_HIGH",
      "current_min_moisture": 0.29,
      "predicted_6h_moisture": 0.096,
      "fao56_etc_mm_hr": 0.375,
      "rain_probability_8h": 0.12,
      "crop": "Ginger (Kc=1.10)",
      "root_depth_m": 0.35,
      "recommended_pulse_cycle": "3 Bursts: 15 min ON / 20 min SOAK"
    },
    "Valve_C": {
      "zone_name": "Lower Valley Basin",
      "irrigation_need_score": 0.606,
      "actuator_status": "MODERATE_IRRIGATION",
      "current_min_moisture": 0.396,
      "predicted_6h_moisture": 0.216,
      "fao56_etc_mm_hr": 0.37,
      "rain_probability_8h": 0.12,
      "crop": "Ginger (Kc=1.10)",
      "root_depth_m": 0.35,
      "recommended_pulse_cycle": "2 Bursts: 10 min ON / 20 min SOAK"
    }
  }
}
```

---

### 2. `POST /api/calibrate_sensor?raw_adc=1650`
Utility endpoint for testing raw analog ADC readings from soil moisture probes.
```json
{
  "raw_adc": 1650.0,
  "calibrated_moisture_percentage": 33.82,
  "calibrated_moisture_index": 0.3382,
  "status": "Dry"
}
```

---

### 3. `GET /api/demo_payload`
Returns a ready-to-test JSON template that microcontrollers (e.g. ESP32, LoRa gateways) can send.

---

### 4. `GET /health`
Returns the status of the loaded ML model (`rf_moisture_decay_model.pkl`) and GeoTIFF raster.
