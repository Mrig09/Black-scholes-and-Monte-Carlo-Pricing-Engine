# Quant Pricing Dashboard (Black-Scholes + Monte Carlo)

A mini Bloomberg-style option pricing and diagnostics dashboard with:
- FastAPI backend for pricing and numerical diagnostics
- Frontend quant dashboard with parameter controls, metrics, and charts

## Features

### Backend API endpoints
- `POST /price`
- `POST /montecarlo`
- `POST /spot-curve`
- `POST /convergence`
- `POST /greeks`
- `POST /implied-vol`
- `POST /runtime-profile`
- `GET /health`

### Frontend
- Parameter input panel with validation
- Pricing summary metrics
- 5+ charts:
  1. Price vs Spot (BS vs MC)
  2. Monte Carlo convergence (log-log)
  3. Greeks vs Spot (Delta/Gamma/Vega, analytic vs numerical)
  4. Implied vol solver trace
  5. Confidence interval visualization
  6. Runtime vs paths

## Run locally

1. Create and activate a Python virtual environment.
2. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```
3. Start server:
   ```bash
   uvicorn backend.app.main:app --reload
   ```
4. Open:
   - App: `http://127.0.0.1:8000/`
   - API docs: `http://127.0.0.1:8000/docs`
