from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

SKIP_WORDS = {"collect", "t", "e"}
MAX_LEN = 40
UPSCALE_TO_H = 90
READ_TIMEOUT_SEC = 8.0
_STRIP = re.compile(r"[^A-Za-z0-9 '\-.]")


def pick_name(lines) -> str | None:
    for line in lines:
        text = " ".join(_STRIP.sub("", str(line)).split())[:MAX_LEN].strip(" .-'")
        if sum(ch.isalpha() for ch in text) >= 2 and text.lower() not in SKIP_WORDS:
            return text
    return None


def _upscale(crop: np.ndarray, target_h: int = UPSCALE_TO_H) -> np.ndarray:
    h = crop.shape[0]
    scale = max(1.0, min(4.0, target_h / float(max(1, h))))
    if scale <= 1.0:
        return crop
    return cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


if sys.platform == "win32":
    SCRIPT = Path(__file__).resolve().parent / "name_reader.ps1"

    class _Engine:
        def __init__(self) -> None:
            self._proc: subprocess.Popen | None = None
            self._lines: queue.Queue = queue.Queue()
            self._next_id = 0
            self._dir = Path(tempfile.gettempdir())
            self._left: list[Path] = []

        def _start(self) -> None:
            self._proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._lines = queue.Queue()
            proc, lines = self._proc, self._lines

            def pump() -> None:
                for line in proc.stdout:
                    lines.put(line.rstrip("\r\n"))

            threading.Thread(target=pump, daemon=True).start()

        def warm(self) -> str:
            if self._proc is None or self._proc.poll() is not None:
                self._start()
            return ""

        def read(self, crop: np.ndarray) -> tuple[list[str], str]:
            self._clean()
            self._next_id += 1
            tag = str(self._next_id)
            image = self._dir / f"s2f-name-{os.getpid()}-{tag}.png"
            if not cv2.imwrite(str(image), _upscale(crop)):
                return [], "couldn't write the temp picture"
            self._left.append(image)
            try:
                self.warm()
                self._proc.stdin.write(f"{tag}|{image}\n")
                self._proc.stdin.flush()
                end = time.monotonic() + READ_TIMEOUT_SEC
                while True:
                    got, _, text = self._lines.get(timeout=max(0.01, end - time.monotonic())).partition("|")
                    if got == tag:
                        self._clean()
                        return text.split("|"), ""
            except (OSError, ValueError, queue.Empty):
                self.stop()
                return [], "Windows text reader didn't answer"

        def stop(self) -> None:
            proc, self._proc = self._proc, None
            if proc is not None and proc.poll() is None:
                try:
                    proc.stdin.close()
                    proc.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    proc.kill()
            self._clean()

        def _clean(self) -> None:
            keep = []
            for image in self._left:
                try:
                    image.unlink(missing_ok=True)
                except OSError:
                    keep.append(image)
            self._left = keep

elif sys.platform == "darwin":
    class _Engine:
        def __init__(self) -> None:
            self._vision = None
            self._why = ""

        def warm(self) -> str:
            if self._vision is None and not self._why:
                try:
                    import Foundation
                    import objc
                    import Vision

                    self._vision = (Vision, Foundation, objc)
                except Exception:
                    self._why = "the Vision package is missing, run Setup.command again"
            return self._why

        def read(self, crop: np.ndarray) -> tuple[list[str], str]:
            if self.warm():
                return [], self._why
            Vision, Foundation, objc = self._vision
            ok, png = cv2.imencode(".png", _upscale(crop))
            if not ok:
                return [], "couldn't encode the picture"
            raw = png.tobytes()
            with objc.autorelease_pool():
                data = Foundation.NSData.dataWithBytes_length_(raw, len(raw))
                handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, {})
                req = Vision.VNRecognizeTextRequest.alloc().init()
                req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
                req.setUsesLanguageCorrection_(False)
                done = handler.performRequests_error_([req], None)
                if not (done[0] if isinstance(done, tuple) else done):
                    return [], "macOS text reader failed"
                found = []
                for obs in req.results() or []:
                    top = obs.topCandidates_(1)
                    if top:
                        found.append((-float(obs.boundingBox().origin.y), str(top[0].string())))
            return [text for _, text in sorted(found)], ""

        def stop(self) -> None:
            pass

else:
    class _Engine:
        def warm(self) -> str:
            if shutil.which("tesseract") is None:
                return "tesseract is not installed (sudo apt install tesseract-ocr)"
            return ""

        def read(self, crop: np.ndarray) -> tuple[list[str], str]:
            why = self.warm()
            if why:
                return [], why
            grey = cv2.cvtColor(_upscale(crop, 120), cv2.COLOR_BGR2GRAY)
            _, bw = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            if cv2.countNonZero(bw) < bw.size / 2:
                bw = cv2.bitwise_not(bw)
            bw = cv2.copyMakeBorder(bw, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
            ok, png = cv2.imencode(".png", bw)
            if not ok:
                return [], "couldn't encode the picture"
            try:
                out = subprocess.run(
                    ["tesseract", "stdin", "stdout", "--psm", "6", "-l", "eng"],
                    input=png.tobytes(), capture_output=True, timeout=READ_TIMEOUT_SEC,
                )
            except (OSError, subprocess.TimeoutExpired):
                return [], "tesseract didn't answer"
            return out.stdout.decode("utf-8", "replace").splitlines(), ""

        def stop(self) -> None:
            pass


class NameReader:
    def __init__(self) -> None:
        self._engine = _Engine()
        self._lock = threading.Lock()
        self.why = ""

    def warm(self) -> None:
        with self._lock:
            try:
                self.why = self._engine.warm()
            except Exception as exc:
                self.why = str(exc)

    def _lines(self, crop: np.ndarray | None) -> tuple[list[str] | None, str]:
        if crop is None or crop.size == 0:
            return None, "nothing to read"
        with self._lock:
            try:
                return self._engine.read(np.ascontiguousarray(crop))
            except Exception as exc:
                return [], str(exc)

    def read(self, crop: np.ndarray | None) -> str | None:
        lines, self.why = self._lines(crop)
        if lines is None:
            return None
        name = pick_name(lines)
        if name is None and not self.why:
            self.why = "no text found in the name area"
        return name

    def read_text(self, crop: np.ndarray | None) -> tuple[str | None, str]:
        lines, why = self._lines(crop)
        if lines is None or why:
            return None, why
        return " ".join(" ".join(str(line).split()) for line in lines).strip(), ""

    def stop(self) -> None:
        with self._lock:
            try:
                self._engine.stop()
            except Exception:
                pass
