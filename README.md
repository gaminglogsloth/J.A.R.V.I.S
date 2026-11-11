# J.A.R.V.I.S.

A local Python server for the single-file HUD and knowledge brain. The HUD is the default view; the gold brain appears only after an explicit brain command. The server binds to `127.0.0.1` and uses only Python's standard library.

## Setup

1. Use Python 3.10 or newer.
2. Copy `.env.example` to `.env` and set `OPENAI_API_KEY` to an API key from your OpenAI developer account. The key is read only by the local Python server and is never sent to the browser. `OPENAI_MODEL` is optional and defaults to `gpt-4o-mini`.
3. Start the UI:

   ```sh
   python3 jarvis_ui/server.py
   ```

4. Open <http://127.0.0.1:8765/>. If port 8765 is occupied, use `JARVIS_PORT=8766 python3 jarvis_ui/server.py` and open port 8766 instead.

The AI uses the OpenAI Responses API. If the key is absent or the request fails, J.A.R.V.I.S. gives a friendly local fallback. The most recent ten user/assistant turns are held in server memory. Taught notes are stored in `notes.json` locally and excluded from Git. No dependency or API key is committed.

## Voice

Voice input requires a browser that supports the Web Speech API, microphone permission, and a secure context. `localhost` and `127.0.0.1` are suitable local contexts. Click the microphone to start/stop listening. The optional **WAKE** toggle filters voice input for “Jarvis”; with it off, recognized commands are handled directly. Spoken replies use browser speech synthesis and can be silenced with **SOUND**.

## Commands

- `show brain`, `open the brain`, `show your knowledge brain`, or `brain` — show the gold knowledge view.
- `hide brain`, `back`, or `interface` — return to the cyan HUD.
- `time` / `what time is it`; `date` / `what is the date` — local clock commands.
- `remember that ...` — save a note and flash its brain node on the next brain view.
- `forget ...` — remove notes whose title or text matches the topic.
- `what do you know about ...` — show and highlight a matching note or repository feature; otherwise ask the AI.
- `open website example.com` or `open https://example.com` — ask for confirmation, then open a new tab after `yes` or the **YES** button. Say/type `no` or use **NO** to cancel.
- `web search for ...` — ask for confirmation before opening search results.
- `system status` / `status` — report available CPU load, memory, and battery readings.
- `set timer for 5 minutes` or `timer 30 seconds` — start a timer.
- Any other text is sent to the AI backend. Opening local apps and files is not supported by this web UI.

Click a visible brain node to show its associated note or feature description. Reduced-motion settings stop automatic brain drift and CSS animation.
