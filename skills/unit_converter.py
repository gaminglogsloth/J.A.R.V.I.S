"""Small deterministic unit converter; it has no side effects."""
import re

name = "Unit converter"
trigger_phrases = [r"\bconvert\b"]
capabilities = []

_LENGTH = {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0, "in": 0.0254, "inch": 0.0254, "inches": 0.0254, "ft": 0.3048, "feet": 0.3048, "mi": 1609.344, "mile": 1609.344, "miles": 1609.344}
_MASS = {"mg": 0.001, "g": 1.0, "kg": 1000.0, "oz": 28.349523125, "lb": 453.59237, "lbs": 453.59237}


def handler(text):
    match = re.search(r"convert\s+([-+]?\d+(?:\.\d+)?)\s*([a-z]+)\s+to\s+([a-z]+)", text, re.I)
    if not match:
        return "Please say, for example, ‘convert 5 km to miles’, sir."
    amount, source, target = float(match.group(1)), match.group(2).casefold(), match.group(3).casefold()
    if source in ("c", "celsius") and target in ("f", "fahrenheit"):
        value, label = amount * 9 / 5 + 32, "°F"
    elif source in ("f", "fahrenheit") and target in ("c", "celsius"):
        value, label = (amount - 32) * 5 / 9, "°C"
    elif source in _LENGTH and target in _LENGTH:
        value, label = amount * _LENGTH[source] / _LENGTH[target], target
    elif source in _MASS and target in _MASS:
        value, label = amount * _MASS[source] / _MASS[target], target
    else:
        return "I can't convert those units yet, sir. I support common length, mass, and Celsius/Fahrenheit conversions."
    return f"{amount:g} {source} is {value:.4g} {label}, sir."
