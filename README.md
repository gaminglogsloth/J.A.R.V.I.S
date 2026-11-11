# J.A.R.V.I.S.

This repository was empty when the interface work began, so there was no existing assistant entry point or command implementation to connect. The interface is a standalone local web UI with an assistant integration point.

## Run

Requires Python 3; no packages or external assets are used.

```sh
python3 jarvis_ui/server.py
```

Open http://127.0.0.1:8765/jarvis.html. The server binds to loopback only.

Type `show brain`, `open the brain`, `show your knowledge brain`, or `brain` to open the knowledge visualization. Use `hide brain`, `back`, `interface`, or any regular command to return to the HUD. Voice input appears when the browser supports the Web Speech API.

## Assistant integration

Normal commands are sent to `POST /api/respond`. Connect the assistant implementation in `respond()` in `jarvis_ui/server.py`; there is no assistant logic in the repository yet, so the current endpoint returns a setup message.
