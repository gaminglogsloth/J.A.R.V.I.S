import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import warnings
from unittest import mock
from urllib.error import URLError

from jarvis_ui import knowledge, server


class KnowledgeTests(unittest.TestCase):
    def test_chunks_have_overlap_and_bounds(self):
        chunks = knowledge.chunk_text(" ".join(f"w{i}" for i in range(1120)), 500, 50)
        self.assertEqual([len(chunk.split()) for chunk in chunks], [500, 500, 220])
        self.assertEqual(chunks[0].split()[-50:], chunks[1].split()[:50])

    def test_reindexes_only_changed_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "docs"
            root.mkdir()
            doc = root / "guide.txt"
            index = Path(temp) / "index.json"
            doc.write_text("local stars and navigation", encoding="utf-8")
            original = knowledge._extract_text
            with mock.patch.object(knowledge, "_extract_text", wraps=original) as extract:
                first = knowledge.build_index(root, index)
                second = knowledge.build_index(root, index)
                self.assertEqual(extract.call_count, 1)
                self.assertEqual(first["changed"], 1)
                self.assertEqual(second["unchanged"], 1)
                doc.write_text("local planets and navigation", encoding="utf-8")
                third = knowledge.build_index(root, index)
                self.assertEqual(extract.call_count, 2)
                self.assertEqual(third["changed"], 1)

    def test_retrieval_ranks_matching_chunk(self):
        files = {
            "space.txt": {"chunks": ["Navigation engines use star charts for deep space travel."], "summary": "Star charts guide travel."},
            "garden.txt": {"chunks": ["Tomatoes need sunlight and watering in the garden."], "summary": "Garden care."},
        }
        results = knowledge.search_chunks("how do star charts guide navigation", files)
        self.assertTrue(results)
        self.assertEqual(results[0]["source"], "space.txt")


class SkillTests(unittest.TestCase):
    def test_loader_accepts_good_and_skips_broken(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "good.py").write_text(
                'import re\nname="Example"\ntrigger_phrases=[r"\\bhello\\b"]\ncapabilities=[]\ndef handler(text): return "hello"\n',
                encoding="utf-8",
            )
            (root / "broken.py").write_text("this is not valid python !!!", encoding="utf-8")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                loaded = server.load_skills(root)
            self.assertEqual([skill["name"] for skill in loaded], ["Example"])
            self.assertEqual(len(caught), 1)

    def test_undeclared_network_skill_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "unsafe.py").write_text(
                'import urllib.request\nname="Unsafe"\ntrigger_phrases=[r"unsafe"]\ncapabilities=[]\ndef handler(text): return "no"\n',
                encoding="utf-8",
            )
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self.assertEqual(server.load_skills(temp), [])
            self.assertEqual(len(caught), 1)

    def test_capability_skill_waits_for_confirmation(self):
        calls = []
        skill = {"name": "Network Example", "triggers": [__import__("re").compile(r"network demo", __import__("re").I)], "capabilities": ["network"], "handler": lambda text: calls.append(text) or "done"}
        old_skills, old_pending = server.SKILLS, server.PENDING_SKILL
        try:
            server.SKILLS = [skill]
            server.PENDING_SKILL = None
            result = server.respond("network demo")
            self.assertIn("Shall I proceed, sir?", result["reply"])
            self.assertEqual(calls, [])
            confirmed = server.respond("yes sir")
            self.assertEqual(confirmed["reply"], "done")
            self.assertEqual(calls, ["network demo"])
        finally:
            server.SKILLS, server.PENDING_SKILL = old_skills, old_pending


class RoutingTests(unittest.TestCase):
    def test_mode_command_runs_before_skills(self):
        with mock.patch.object(server, "_skill_command", side_effect=AssertionError("skill ran before mode")):
            response = server.respond("Open the brain")
        self.assertEqual(response["action"]["type"], "show_brain")

    def test_skill_runs_before_knowledge_and_ai(self):
        expected = {"reply": "skill", "speak": True}
        with mock.patch.object(server, "_skill_command", return_value=expected), \
             mock.patch.object(server, "_knowledge_lookup", side_effect=AssertionError("knowledge ran before skill")), \
             mock.patch.object(server, "_ai_reply", side_effect=AssertionError("AI ran before skill")):
            self.assertEqual(server.respond("try test skill"), expected)

    def test_knowledge_runs_before_ai(self):
        expected = {"reply": "local source", "speak": True}
        with mock.patch.object(server, "_skill_command", return_value=None), \
             mock.patch.object(server, "_note_command", return_value=None), \
             mock.patch.object(server, "_local_clock", return_value=None), \
             mock.patch.object(server, "_knowledge_lookup", return_value=expected), \
             mock.patch.object(server, "_ai_reply", side_effect=AssertionError("AI ran before knowledge")):
            self.assertEqual(server.respond("a local question"), expected)

    def test_ai_network_failure_is_friendly_and_redacted(self):
        with mock.patch.dict(server.os.environ, {"OPENAI_API_KEY": "not-a-real-key"}), \
             mock.patch.object(server, "urlopen", side_effect=URLError("offline")):
            answer, unavailable = server._ai_reply("hello")
        self.assertTrue(unavailable)
        self.assertIn("can't reach my AI service", answer)
        self.assertNotIn("not-a-real-key", answer)

    def test_tts_credentials_stay_server_side_and_errors_are_friendly(self):
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _limit): return b"mp3-data"

        with mock.patch.dict(server.os.environ, {"FISH_API_KEY": "test-secret"}), \
             mock.patch.object(server, "urlopen", return_value=FakeResponse()) as request_call:
            audio, error = server._fish_tts("Systems online, sir.")
        self.assertEqual(audio, b"mp3-data")
        self.assertIsNone(error)
        request = request_call.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertNotIn("test-secret", request.data.decode())
        with mock.patch.dict(server.os.environ, {"FISH_API_KEY": "test-secret"}), \
             mock.patch.object(server, "urlopen", side_effect=URLError("offline")):
            audio, error = server._fish_tts("Systems online, sir.")
        self.assertIsNone(audio)
        self.assertIn("unavailable", error)


class ModeRuleTests(unittest.TestCase):
    def test_explicit_brain_open_and_close_phrases(self):
        for phrase in ("show brain", "open the brain", "brain"):
            with self.subTest(phrase=phrase):
                self.assertEqual(server._mode_command(phrase)["action"]["type"], "show_brain")
        for phrase in ("back", "hide brain"):
            with self.subTest(phrase=phrase):
                self.assertEqual(server._mode_command(phrase)["action"]["type"], "hide_brain")

    def test_normal_commands_do_not_open_brain_and_page_load_starts_hud(self):
        for phrase in ("time", "what is the weather", "remember that the sky is blue"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(server._mode_command(phrase))
        html = (Path(server.APP_DIR) / "jarvis.html").read_text(encoding="utf-8")
        body = html.split("<body", 1)[1].split(">", 1)[0]
        self.assertNotIn("brain-mode", body)
        self.assertIn('class="booting"', body)
        self.assertIn("function startBoot()", html)


if __name__ == "__main__":
    unittest.main()
