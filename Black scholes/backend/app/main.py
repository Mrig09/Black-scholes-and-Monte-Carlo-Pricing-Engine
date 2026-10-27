from __future__ import annotations

import math
import random
import statistics
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator


OptionType = Literal["call", "put"]


class BaseParams(BaseModel):
    spot: float = Field(gt=0)
    strike: float = Field(gt=0)
    maturity: float = Field(gt=0)
    rate: float
    volatility: float = Field(gt=0)
    option_type: OptionType = "call"


class PriceRequest(BaseParams):
    mc_paths: int = Field(default=100_000, ge=1_000, le=2_000_000)
    seed: int | None = None
    antithetic: bool = True


class ConvergenceRequest(BaseParams):
    path_grid: list[int] = Field(default_factory=lambda: [1000, 2500, 5000, 10000, 25000, 50000, 100000])
    seed: int | None = None
    antithetic: bool = True

    @model_validator(mode="after")
    def check_grid(self) -> "ConvergenceRequest":
        if not self.path_grid:
            raise ValueError("path_grid cannot be empty")
        if any(n < 1000 for n in self.path_grid):
            raise ValueError("all path_grid values must be >= 1000")
        return self


class GreeksRequest(BaseParams):
    bump_size: float = Field(default=0.01, gt=0)
    spot_min_factor: float = Field(default=0.5, gt=0)
    spot_max_factor: float = Field(default=1.5, gt=0)
    num_points: int = Field(default=31, ge=11, le=101)


class ImpliedVolRequest(BaseModel):
    spot: float = Field(gt=0)
    strike: float = Field(gt=0)
    maturity: float = Field(gt=0)
    rate: float
    market_price: float = Field(gt=0)
    option_type: OptionType = "call"
    initial_guess: float = Field(default=0.2, gt=0)
    tolerance: float = Field(default=1e-6, gt=0)
    max_iterations: int = Field(default=30, ge=1, le=100)


class SpotCurveRequest(BaseParams):
    mc_paths: int = Field(default=30000, ge=5000, le=500000)
    seed: int | None = None
    antithetic: bool = True
    min_factor: float = Field(default=0.5, gt=0)
    max_factor: float = Field(default=1.5, gt=0)
    num_points: int = Field(default=25, ge=11, le=81)


class RuntimeProfileRequest(BaseParams):
    path_grid: list[int] = Field(default_factory=lambda: [10_000, 100_000, 1_000_000])
    seed: int | None = None
    antithetic: bool = True


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_price(
    spot: float,
    strike: float,
    maturity: float,
    rate: float,
    volatility: float,
    option_type: OptionType,
) -> float:
    sigma_sqrt_t = volatility * math.sqrt(maturity)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility * volatility) * maturity) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t

    if option_type == "call":
        return spot * norm_cdf(d1) - strike * math.exp(-rate * maturity) * norm_cdf(d2)
    return strike * math.exp(-rate * maturity) * norm_cdf(-d2) - spot * norm_cdf(-d1)


def black_scholes_greeks(
    spot: float,
    strike: float,
    maturity: float,
    rate: float,
    volatility: float,
    option_type: OptionType,
) -> dict[str, float]:
    sigma_sqrt_t = volatility * math.sqrt(maturity)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility * volatility) * maturity) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t
    pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)

    if option_type == "call":
        delta = norm_cdf(d1)
    else:
        delta = norm_cdf(d1) - 1.0

    gamma = pdf_d1 / (spot * sigma_sqrt_t)
    vega = spot * pdf_d1 * math.sqrt(maturity)

    theta_first = -(spot * pdf_d1 * volatility) / (2.0 * math.sqrt(maturity))
    if option_type == "call":
        theta = theta_first - rate * strike * math.exp(-rate * maturity) * norm_cdf(d2)
        rho = strike * maturity * math.exp(-rate * maturity) * norm_cdf(d2)
    else:
        theta = theta_first + rate * strike * math.exp(-rate * maturity) * norm_cdf(-d2)
        rho = -strike * maturity * math.exp(-rate * maturity) * norm_cdf(-d2)

    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "rho": rho,
    }


def monte_carlo_price(
    spot: float,
    strike: float,
    maturity: float,
    rate: float,
    volatility: float,
    option_type: OptionType,
    paths: int,
    seed: int | None,
    antithetic: bool,
) -> dict[str, float | list[float]]:
    rng = random.Random(seed)
    drift = (rate - 0.5 * volatility * volatility) * maturity
    diffusion = volatility * math.sqrt(maturity)
    discount = math.exp(-rate * maturity)

    payoffs: list[float] = []
    start = time.perf_counter()

    if antithetic:
        half_paths = (paths + 1) // 2
        for _ in range(half_paths):
            z = rng.gauss(0.0, 1.0)
            st1 = spot * math.exp(drift + diffusion * z)
            st2 = spot * math.exp(drift - diffusion * z)
            if option_type == "call":
                payoffs.append(max(st1 - strike, 0.0))
                payoffs.append(max(st2 - strike, 0.0))
            else:
                payoffs.append(max(strike - st1, 0.0))
                payoffs.append(max(strike - st2, 0.0))
        payoffs = payoffs[:paths]
    else:
        for _ in range(paths):
            z = rng.gauss(0.0, 1.0)
            st = spot * math.exp(drift + diffusion * z)
            if option_type == "call":
                payoffs.append(max(st - strike, 0.0))
            else:
                payoffs.append(max(strike - st, 0.0))

    discounted_payoffs = [discount * p for p in payoffs]
    mc_price = statistics.fmean(discounted_payoffs)
    sample_stdev = statistics.stdev(discounted_payoffs)
    std_error = sample_stdev / math.sqrt(paths)
    ci_low = mc_price - 1.96 * std_error
    ci_high = mc_price + 1.96 * std_error
    runtime_ms = (time.perf_counter() - start) * 1000

    return {
        "mc_price": mc_price,
        "confidence_interval": [ci_low, ci_high],
        "standard_error": std_error,
        "sample_stdev": sample_stdev,
        "runtime_ms": runtime_ms,
    }


def finite_difference_greeks(
    spot: float,
    strike: float,
    maturity: float,
    rate: float,
    volatility: float,
    option_type: OptionType,
    bump: float,
) -> dict[str, float]:
    ds = max(spot * bump, 1e-6)
    dv = max(volatility * bump, 1e-6)

    p0 = black_scholes_price(spot, strike, maturity, rate, volatility, option_type)
    p_up = black_scholes_price(spot + ds, strike, maturity, rate, volatility, option_type)
    p_down = black_scholes_price(max(spot - ds, 1e-6), strike, maturity, rate, volatility, option_type)

    vol_up = black_scholes_price(spot, strike, maturity, rate, volatility + dv, option_type)
    vol_down = black_scholes_price(spot, strike, maturity, rate, max(volatility - dv, 1e-6), option_type)

    delta = (p_up - p_down) / (2.0 * ds)
    gamma = (p_up - 2.0 * p0 + p_down) / (ds * ds)
    vega = (vol_up - vol_down) / (2.0 * dv)

    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
    }


def warnings_for_inputs(paths: int, maturity: float, volatility: float) -> list[str]:
    warnings: list[str] = []
    if paths < 10_000:
        warnings.append("Monte Carlo paths are low; confidence interval may be wide.")
    if maturity < 0.05:
        warnings.append("Very short maturity can create unstable finite-difference Greeks.")
    if volatility > 1.0:
        warnings.append("High volatility regime detected; consider increasing path count.")
    return warnings


app = FastAPI(title="Quant Pricing Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/price")
def price_option(payload: PriceRequest) -> dict:
    bs_start = time.perf_counter()
    bs_price = black_scholes_price(
        payload.spot,
        payload.strike,
        payload.maturity,
        payload.rate,
        payload.volatility,
        payload.option_type,
    )
    bs_runtime_ms = (time.perf_counter() - bs_start) * 1000

    mc = monte_carlo_price(
        payload.spot,
        payload.strike,
        payload.maturity,
        payload.rate,
        payload.volatility,
        payload.option_type,
        payload.mc_paths,
        payload.seed,
        payload.antithetic,
    )

    return {
        "bs_price": bs_price,
        "mc_price": mc["mc_price"],
        "confidence_interval": mc["confidence_interval"],
        "standard_error": mc["standard_error"],
        "error_vs_bs": abs(mc["mc_price"] - bs_price),
        "diagnostics": {
            "bs_runtime_ms": bs_runtime_ms,
            "mc_runtime_ms": mc["runtime_ms"],
            "variance_reduction": "antithetic" if payload.antithetic else "none",
            "warnings": warnings_for_inputs(payload.mc_paths, payload.maturity, payload.volatility),
            "seed": payload.seed,
            "paths": payload.mc_paths,
        },
    }


@app.post("/montecarlo")
def montecarlo_only(payload: PriceRequest) -> dict:
    mc = monte_carlo_price(
        payload.spot,
        payload.strike,
        payload.maturity,
        payload.rate,
        payload.volatility,
        payload.option_type,
        payload.mc_paths,
        payload.seed,
        payload.antithetic,
    )
    return {
        **mc,
        "diagnostics": {
            "variance_reduction": "antithetic" if payload.antithetic else "none",
            "warnings": warnings_for_inputs(payload.mc_paths, payload.maturity, payload.volatility),
            "seed": payload.seed,
            "paths": payload.mc_paths,
        },
    }


@app.post("/spot-curve")
def spot_curve(payload: SpotCurveRequest) -> dict:
    spots = [
        payload.spot * (payload.min_factor + (payload.max_factor - payload.min_factor) * i / (payload.num_points - 1))
        for i in range(payload.num_points)
    ]

    bs_prices: list[float] = []
    mc_prices: list[float] = []

    for i, s in enumerate(spots):
        bs_prices.append(
            black_scholes_price(
                s,
                payload.strike,
                payload.maturity,
                payload.rate,
                payload.volatility,
                payload.option_type,
            )
        )
        mc = monte_carlo_price(
            s,
            payload.strike,
            payload.maturity,
            payload.rate,
            payload.volatility,
            payload.option_type,
            payload.mc_paths,
            None if payload.seed is None else payload.seed + i,
            payload.antithetic,
        )
        mc_prices.append(mc["mc_price"])

    return {
        "spot": spots,
        "bs_price": bs_prices,
        "mc_price": mc_prices,
        "diagnostics": {
            "paths_per_point": payload.mc_paths,
            "num_points": payload.num_points,
            "variance_reduction": "antithetic" if payload.antithetic else "none",
        },
    }


@app.post("/convergence")
def convergence(payload: ConvergenceRequest) -> dict:
    bs_price = black_scholes_price(
        payload.spot,
        payload.strike,
        payload.maturity,
        payload.rate,
        payload.volatility,
        payload.option_type,
    )

    rows = []
    for i, n in enumerate(payload.path_grid):
        mc = monte_carlo_price(
            payload.spot,
            payload.strike,
            payload.maturity,
            payload.rate,
            payload.volatility,
            payload.option_type,
            n,
            None if payload.seed is None else payload.seed + i,
            payload.antithetic,
        )
        rows.append(
            {
                "paths": n,
                "mc_price": mc["mc_price"],
                "abs_error": abs(mc["mc_price"] - bs_price),
                "standard_error": mc["standard_error"],
                "runtime_ms": mc["runtime_ms"],
            }
        )

    log_x = [math.log(r["paths"]) for r in rows]
    log_y = [math.log(max(r["abs_error"], 1e-14)) for r in rows]
    n_rows = len(rows)
    sum_x = sum(log_x)
    sum_y = sum(log_y)
    sum_xy = sum(x * y for x, y in zip(log_x, log_y))
    sum_x2 = sum(x * x for x in log_x)
    denom = n_rows * sum_x2 - sum_x * sum_x
    slope = (n_rows * sum_xy - sum_x * sum_y) / denom if denom != 0 else float("nan")

    return {
        "bs_price": bs_price,
        "series": rows,
        "diagnostics": {
            "loglog_error_slope": slope,
            "variance_reduction": "antithetic" if payload.antithetic else "none",
            "warnings": warnings_for_inputs(min(payload.path_grid), payload.maturity, payload.volatility),
        },
    }


@app.post("/greeks")
def greeks(payload: GreeksRequest) -> dict:
    spots = [
        payload.spot * (payload.spot_min_factor + (payload.spot_max_factor - payload.spot_min_factor) * i / (payload.num_points - 1))
        for i in range(payload.num_points)
    ]

    analytic = {"delta": [], "gamma": [], "vega": []}
    numerical = {"delta": [], "gamma": [], "vega": []}

    for s in spots:
        a = black_scholes_greeks(
            s,
            payload.strike,
            payload.maturity,
            payload.rate,
            payload.volatility,
            payload.option_type,
        )
        n = finite_difference_greeks(
            s,
            payload.strike,
            payload.maturity,
            payload.rate,
            payload.volatility,
            payload.option_type,
            payload.bump_size,
        )
        for key in ("delta", "gamma", "vega"):
            analytic[key].append(a[key])
            numerical[key].append(n[key])

    point_analytic = black_scholes_greeks(
        payload.spot,
        payload.strike,
        payload.maturity,
        payload.rate,
        payload.volatility,
        payload.option_type,
    )
    point_numerical = finite_difference_greeks(
        payload.spot,
        payload.strike,
        payload.maturity,
        payload.rate,
        payload.volatility,
        payload.option_type,
        payload.bump_size,
    )

    return {
        "spot": spots,
        "analytic": analytic,
        "numerical": numerical,
        "point": {
            "analytic": point_analytic,
            "numerical": point_numerical,
        },
        "diagnostics": {
            "bump_size": payload.bump_size,
            "num_points": payload.num_points,
        },
    }


@app.post("/implied-vol")
def implied_vol(payload: ImpliedVolRequest) -> dict:
    sigma = payload.initial_guess
    trace = []
    converged = False
    warning = None

    for i in range(payload.max_iterations):
        model_price = black_scholes_price(
            payload.spot,
            payload.strike,
            payload.maturity,
            payload.rate,
            sigma,
            payload.option_type,
        )
        greeks = black_scholes_greeks(
            payload.spot,
            payload.strike,
            payload.maturity,
            payload.rate,
            sigma,
            payload.option_type,
        )
        diff = model_price - payload.market_price
        trace.append(
            {
                "iteration": i,
                "sigma": sigma,
                "model_price": model_price,
                "residual": diff,
            }
        )

        if abs(diff) < payload.tolerance:
            converged = True
            break

        vega = greeks["vega"]
        if abs(vega) < 1e-10:
            warning = "Vega is too small; Newton step became unstable."
            break

        sigma = max(sigma - diff / vega, 1e-6)

    return {
        "implied_volatility": sigma,
        "converged": converged,
        "iterations": len(trace),
        "trace": trace,
        "diagnostics": {
            "tolerance": payload.tolerance,
            "max_iterations": payload.max_iterations,
            "warning": warning,
        },
    }


@app.post("/runtime-profile")
def runtime_profile(payload: RuntimeProfileRequest) -> dict:
    rows = []
    for i, n in enumerate(payload.path_grid):
        mc = monte_carlo_price(
            payload.spot,
            payload.strike,
            payload.maturity,
            payload.rate,
            payload.volatility,
            payload.option_type,
            n,
            None if payload.seed is None else payload.seed + i,
            payload.antithetic,
        )
        rows.append(
            {
                "paths": n,
                "runtime_ms": mc["runtime_ms"],
                "standard_error": mc["standard_error"],
            }
        )

    return {
        "series": rows,
        "diagnostics": {
            "variance_reduction": "antithetic" if payload.antithetic else "none",
        },
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
def serve_frontend() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")
