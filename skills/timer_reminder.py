"""Local timer and reminder skill; it does not access files or the network."""
name = "Timer and reminder"
trigger_phrases = [r"\b(?:set\s+)?timer\b", r"\bremind me in\b"]
capabilities = []


def handler(text):
    return "I can set a local timer or reminder, sir."
