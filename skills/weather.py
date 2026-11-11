"""Weather skill placeholder. No network calls or data sharing are performed."""
name = "Weather"
trigger_phrases = [r"\b(?:weather|forecast)\b"]
capabilities = []


def handler(text):
    return "The weather skill is ready, sir, but no weather provider is configured. I have not sent a location or request anywhere."
