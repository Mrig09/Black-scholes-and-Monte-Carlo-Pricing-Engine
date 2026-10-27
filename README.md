Quant Pricing Dashboard (Black-Scholes + Monte Carlo)
A mini Bloomberg-style option pricing and diagnostics dashboard with:

FastAPI backend for pricing and numerical diagnostics
Frontend quant dashboard with parameter controls, metrics, and charts
Features
Backend API endpoints
POST /price
POST /montecarlo
POST /spot-curve
POST /convergence
POST /greeks
POST /implied-vol
POST /runtime-profile
GET /health
Frontend
Parameter input panel with validation
Pricing summary metrics
5+ charts:
Price vs Spot (BS vs MC)
Monte Carlo convergence (log-log)
Greeks vs Spot (Delta/Gamma/Vega, analytic vs numerical)
Implied vol solver trace
Confidence interval visualization
Runtime vs paths
Run locally
Create and activate a Python virtual environment.
Install dependencies:
pip install -r backend/requirements.txt
Start server:
uvicorn backend.app.main:app --reload
Open:
App: http://127.0.0.1:8000/
API docs: http://127.0.0.1:8000/docs
