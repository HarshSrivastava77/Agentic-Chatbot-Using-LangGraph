import ast
import math
import operator
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_tavily import TavilySearch


load_dotenv()


# ============================================================
# TAVILY WEB SEARCH
# ============================================================

search_tool = TavilySearch(
    max_results=5,
    topic="general",
    search_depth="advanced",
)


# ============================================================
# SAVE NOTE
# ============================================================

@tool
def save_note(filename: str, content: str) -> str:
    """
    Save text to a file in the local notes directory.

    Use this only when the user explicitly asks to save a note.
    """
    safe_filename = Path(filename).name

    if not safe_filename:
        return "Please provide a valid filename."

    if not safe_filename.lower().endswith(".txt"):
        safe_filename += ".txt"

    notes_directory = Path(os.getenv("APP_DATA_DIR", ".")) / "notes"
    notes_directory.mkdir(parents=True, exist_ok=True)
    note_path = notes_directory / safe_filename
    note_path.write_text(content, encoding="utf-8")

    return f"Saved note to {note_path}."


# ============================================================
# CALCULATOR
# ============================================================

ALLOWED_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

ALLOWED_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

ALLOWED_FUNCTIONS = {
    "abs": abs,
    "max": max,
    "min": min,
    "round": round,
    "sum": sum,
    **{
        name: getattr(math, name)
        for name in dir(math)
        if not name.startswith("_") and callable(getattr(math, name))
    },
}

ALLOWED_CONSTANTS = {
    name: getattr(math, name)
    for name in ("e", "inf", "nan", "pi", "tau")
}


def _evaluate_math_node(node):
    if isinstance(node, ast.Expression):
        return _evaluate_math_node(node.body)

    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value

    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_BINARY_OPERATORS:
        left = _evaluate_math_node(node.left)
        right = _evaluate_math_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("Exponent is too large.")
        return ALLOWED_BINARY_OPERATORS[type(node.op)](left, right)

    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_UNARY_OPERATORS:
        return ALLOWED_UNARY_OPERATORS[type(node.op)](_evaluate_math_node(node.operand))

    if isinstance(node, ast.Name) and node.id in ALLOWED_CONSTANTS:
        return ALLOWED_CONSTANTS[node.id]

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_evaluate_math_node(element) for element in node.elts]

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = ALLOWED_FUNCTIONS.get(node.func.id)
        if function is None or node.keywords:
            raise ValueError("Function is not allowed.")
        arguments = [_evaluate_math_node(argument) for argument in node.args]
        return function(*arguments)

    raise ValueError("Expression contains unsupported syntax.")

@tool
def calculator(expression: str) -> str:
    """
    Calculate mathematical expressions safely.
    """
    try:
        if len(expression) > 500:
            raise ValueError("Expression is too long.")
        parsed_expression = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(parsed_expression)) > 100:
            raise ValueError("Expression is too complex.")
        result = _evaluate_math_node(parsed_expression)
        return str(result)

    except Exception as e:
        return f"Calculation error: {e}"


# ============================================================
# STOCK PRICE
# ============================================================

@tool
def get_stock_price(symbol: str) -> str:
    """
    Get the latest stock price for a stock symbol.
    Example: AAPL, MSFT, NVDA
    """

    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")

    if not api_key:
        return "ALPHA_VANTAGE_API_KEY is not configured."

    symbol = symbol.strip().upper()

    url = "https://www.alphavantage.co/query"

    params = {
        "function": "GLOBAL_QUOTE",
        "symbol": symbol,
        "apikey": api_key,
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        quote = data.get("Global Quote", {})

        price = quote.get("05. price")

        if price:
            return f"{symbol} current price: ${price}"

        information = data.get("Information")

        if information:
            return f"Alpha Vantage: {information}"

        return f"Could not find stock price for {symbol}."

    except requests.RequestException as e:
        return f"Stock API request failed: {e}"

    except Exception as e:
        return f"Stock tool failed: {e}"


# ============================================================
# SIMULATED STOCK PURCHASE
# ============================================================

@tool
def buy_stock(symbol: str, quantity: int) -> str:
    """
    Simulate buying a whole number of shares without contacting a broker.

    Use this only when the user explicitly asks to buy stock. The application
    must obtain human approval before this tool runs.
    """
    symbol = symbol.strip().upper()

    if not symbol:
        return "A stock symbol is required."

    if quantity <= 0:
        return "Quantity must be a positive whole number."

    return (
        f"Simulated purchase completed: {quantity} share(s) of {symbol}. "
        "No broker was contacted and no real money was spent."
    )


# ============================================================
# WEATHER
# ============================================================

@tool
def get_current_weather(city: str) -> str:
    """
    Get the current weather for a city.
    Example: Delhi, Mumbai, London
    """

    api_key = os.getenv("OPENWEATHER_API_KEY")

    if not api_key:
        return "OPENWEATHER_API_KEY is not configured."

    city = city.strip()

    if not city:
        return "Please provide a city name."

    try:
        # ----------------------------------------------------
        # GEOCODING
        # ----------------------------------------------------

        geo_url = "https://api.openweathermap.org/geo/1.0/direct"

        geo_params = {
            "q": city,
            "limit": 1,
            "appid": api_key,
        }

        geo_response = requests.get(
            geo_url,
            params=geo_params,
            timeout=10,
        )

        geo_response.raise_for_status()

        locations = geo_response.json()

        if not locations:
            return f"Could not find location: {city}"

        latitude = locations[0]["lat"]
        longitude = locations[0]["lon"]

        resolved_name = locations[0].get("name", city)
        country = locations[0].get("country", "")

        # ----------------------------------------------------
        # WEATHER
        # ----------------------------------------------------

        weather_url = "https://api.openweathermap.org/data/2.5/weather"

        weather_params = {
            "lat": latitude,
            "lon": longitude,
            "appid": api_key,
            "units": "metric",
        }

        weather_response = requests.get(
            weather_url,
            params=weather_params,
            timeout=10,
        )

        weather_response.raise_for_status()

        data = weather_response.json()

        temperature = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        humidity = data["main"]["humidity"]
        description = data["weather"][0]["description"]

        return (
            f"Weather in {resolved_name}, {country}: "
            f"{temperature}°C, feels like {feels_like}°C, "
            f"{description}, humidity {humidity}%."
        )

    except requests.RequestException as e:
        return f"Weather API request failed: {e}"

    except Exception as e:
        return f"Weather tool failed: {e}"