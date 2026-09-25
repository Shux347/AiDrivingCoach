"""Phase 5 — text-to-speech delivery.

Speaks a coaching line over the "team radio". Primary path is ``edge-tts``
(Microsoft neural voices, streamed to a temp mp3 then played with macOS's
built-in ``afplay`` — zero extra native deps). Falls back to offline ``pyttsx3``
(or the macOS ``say`` command) when edge-tts or the network is unavailable.

All engines are imported lazily and everything degrades to a console print, so
importing this module never fails and the app runs even with no audio stack.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile

from . import config


class Speaker:
    """Blocking speech synthesis + playback. Safe to call from a worker thread."""

    def __init__(
        self,
        enabled: bool = config.TTS_ENABLED,
        engine: str = config.TTS_ENGINE,
        voice: str = config.TTS_VOICE,
        rate: str = config.TTS_RATE,
    ) -> None:
        self.enabled = enabled
        self.engine = engine
        self.voice = voice
        self.rate = rate

    def say(self, text: str) -> None:
        """Synthesize and play ``text``, blocking until playback finishes."""
        text = text.strip()
        if not text:
            return
        print(f"\n📻  RADIO: {text}\n")
        if not self.enabled:
            return
        if self.engine == "edge" and self._say_edge(text):
            return
        if self._say_pyttsx3(text):
            return
        self._say_macos(text)

    # -- edge-tts (online, neural) ----------------------------------------
    def _say_edge(self, text: str) -> bool:
        try:
            import edge_tts  # noqa: F401
        except Exception:
            return False
        try:
            return bool(asyncio.run(self._edge_async(text)))
        except Exception as exc:  # network / playback failure -> fall back
            print(f"[TTS] edge-tts failed ({exc}); falling back.")
            return False

    async def _edge_async(self, text: str) -> bool:
        import edge_tts

        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch="-2Hz")
        fd, path = tempfile.mkstemp(suffix=".mp3")
        wrote_audio = False
        try:
            with os.fdopen(fd, "wb") as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                        wrote_audio = True
            if not wrote_audio:
                return False  # empty stream -> let a fallback engine try
            return await self._play_file(path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    @staticmethod
    async def _play_file(path: str) -> bool:
        player = shutil.which("afplay") or shutil.which("ffplay") or shutil.which("mpv")
        if player is None:
            print("[TTS] no audio player found (afplay/ffplay/mpv).")
            return False
        args = [player, path]
        if player.endswith("ffplay"):
            args = [player, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
        elif player.endswith("mpv"):
            args = [player, "--no-video", "--really-quiet", path]
        proc = await asyncio.create_subprocess_exec(*args)
        await proc.wait()
        return proc.returncode == 0

    # -- pyttsx3 (offline) -------------------------------------------------
    def _say_pyttsx3(self, text: str) -> bool:
        try:
            import pyttsx3
        except Exception:
            return False
        try:
            engine = pyttsx3.init()
            for v in engine.getProperty("voices"):
                if "Daniel" in getattr(v, "name", ""):  # British male on macOS
                    engine.setProperty("voice", v.id)
                    break
            engine.say(text)
            engine.runAndWait()
            return True
        except Exception as exc:
            print(f"[TTS] pyttsx3 failed ({exc}); falling back.")
            return False

    # -- macOS `say` (last resort, zero deps) ------------------------------
    @staticmethod
    def _say_macos(text: str) -> bool:
        say = shutil.which("say")
        if say is None:
            return False
        try:
            subprocess.run([say, "-v", "Daniel", text], check=False)
            return True
        except Exception:
            return False
