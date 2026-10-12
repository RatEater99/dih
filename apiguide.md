# 🔌 API Integration Guide for Frontend Developers

Base URL: `http://localhost:8000` (or your deployed server URL)  
Interactive OpenAPI/Swagger docs: `http://localhost:8000/docs`

---

## 1. Main Endpoint: `POST /api/predict_irrigation`

Call this endpoint whenever your frontend receives sensor telemetry, polls for decisions, or runs an irrigation check.

### Request
- **Method:** `POST`
- **Headers:** `Content-Type: application/json`
- **Body Example:**
```json
{
  "current_hour": 13.0,
  "packets": [
    {
      "sensor_id": "Ridge_Crest_Node",
      "zone_id": "Valve_A",
      "raw_moisture": 1690,
      "temperature_c": 26.8,
      "coordinates": { "grid_x": 90, "grid_y": 210 }
    },
    {
      "sensor_id": "Mid_Slope_Node",
      "zone_id": "Valve_B",
      "raw_moisture": 1580,
      "temperature_c": 25.4,
      "coordinates": { "grid_x": 180, "grid_y": 126 }
    },
    {
      "sensor_id": "Valley_Basin_Node",
      "zone_id": "Valve_C",
      "raw_moisture": 1440,
      "temperature_c": 23.9,
      "coordinates": { "grid_x": 270, "grid_y": 42 }
    }
  ]
}
```

> **Note on `raw_moisture`:** The backend handles the hardware ADC conversion automatically:
> - `1880` (dry air) -> `0%`
> - `1200` (submerged in water) -> `100%`
> If your hardware already sends normalized moisture (0.0 to 1.0), you can pass `"moisture": 0.35` instead.

---

### Response (`200 OK`)
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

## 2. Key Values for the Frontend UI

| Field | Type | How Frontend Should Display It |
| :--- | :--- | :--- |
| `irrigation_need_score` | `number (0.0 - 1.0)` | Progress bar, gauge, or percentage (`score * 100`) |
| `actuator_status` | `string` | Status badge (`TRIGGER_IRRIGATION_HIGH`, `MODERATE_IRRIGATION`, `STANDBY_OPTIMAL`) |
| `recommended_pulse_cycle`| `string` | Displayed directly under each valve card |
| `current_min_moisture` | `number (0.0 - 1.0)` | Current driest spot in that zone |
| `predicted_6h_moisture` | `number (0.0 - 1.0)` | 6-8 hour ML forecast |
| `rain_prob_8h` | `number (0.0 - 1.0)` | Weather indicator (`12% rain likelihood`) |

---

## 3. Quick Frontend Code Snippets

### JavaScript / TypeScript (`fetch`)
```javascript
const response = await fetch("http://localhost:8000/api/predict_irrigation", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    current_hour: 13.0,
    packets: [
      { sensor_id: "Ridge_Crest_Node", zone_id: "Valve_A", raw_moisture: 1690, temperature_c: 26.8 },
      { sensor_id: "Mid_Slope_Node", zone_id: "Valve_B", raw_moisture: 1580, temperature_c: 25.4 },
      { sensor_id: "Valley_Basin_Node", zone_id: "Valve_C", raw_moisture: 1440, temperature_c: 23.9 }
    ]
  })
});

const data = await response.json();
console.log(data.zones.Valve_A.irrigation_need_score); // 0.922
```

### React Hook Example
```jsx
import { useState, useEffect } from "react";

export function useIrrigationData(sensorPackets) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!sensorPackets?.length) return;
    setLoading(true);

    fetch("http://localhost:8000/api/predict_irrigation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_hour: new Date().getHours(), packets: sensorPackets })
    })
      .then(res => res.json())
      .then(json => {
        setData(json);
        setLoading(false);
      })
      .catch(err => {
        console.error("API error:", err);
        setLoading(false);
      });
  }, [sensorPackets]);

  return { data, loading };
}
```

---

## 4. Helper Endpoints

- **`GET /api/demo_payload`**: Returns a sample JSON payload so your frontend team can test UI rendering before physical hardware is connected.
- **`POST /api/calibrate_sensor?raw_adc=1650`**: Converts raw analog sensor ADC values to moisture percentages on demand.
- **`GET /health`**: Healthcheck endpoint returning API and model status.
