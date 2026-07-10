from fastmcp import FastMCP

mcp = FastMCP("demo-tools")

@mcp.tool()
def get_weather(city: str) -> dict:
    """Get the current weather for a city (stubbed demo data)."""
    fake_db = {
        "mumbai": {"temp_c": 31, "condition": "Humid, partly cloudy"},
        "paris": {"temp_c": 22, "condition": "Clear skies"},
        "london": {"temp_c": 17, "condition": "Light rain"},
    }
    data = fake_db.get(city.lower())
    if not data:
        return {"city": city, "error": "City not in demo database"}
    return {"city": city, **data}

@mcp.tool()
def calculate_sip(monthly_amount: float, years: int, annual_return_pct: float = 12.0) -> dict:
    """Calculate the future value of a monthly SIP investment."""
    r = annual_return_pct / 100 / 12
    n = years * 12
    fv = monthly_amount * (((1 + r) ** n - 1) / r) * (1 + r)
    invested = monthly_amount * n
    return {
        "invested": round(invested, 2),
        "future_value": round(fv, 2),
        "gain": round(fv - invested, 2),
    }

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8765)