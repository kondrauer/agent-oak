"""Emulator state module."""

import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from threading import Lock

from pyboy import PyBoy
from pyboy.utils import WindowEvent

RECORD_FPS = 60
RECORD_SCALE = 3


class FrameRecorder:
    """Stream frames to a video file through an ffmpeg process."""

    def __init__(self, path: Path, width: int, height: int) -> None:
        """Start ffmpeg, it reads raw RGBA frames from stdin.

        Args:
            path: The video file to write, e.g. run.mp4.
            width: Frame width in pixels.
            height: Frame height in pixels.
        """
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("--record needs ffmpeg on the PATH")
        self._ffmpeg = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgba",
                "-s",
                f"{width}x{height}",
                "-r",
                str(RECORD_FPS),
                "-i",
                "-",
                # nearest neighbour keeps the pixel art sharp
                "-vf",
                f"scale=iw*{RECORD_SCALE}:ih*{RECORD_SCALE}:flags=neighbor",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            stdin=subprocess.PIPE,
        )

    def add_frame(self, frame: bytes) -> None:
        """Append one raw RGBA frame."""
        assert self._ffmpeg.stdin is not None
        self._ffmpeg.stdin.write(frame)

    def close(self) -> None:
        """Flush the remaining frames and finish the video file."""
        assert self._ffmpeg.stdin is not None
        self._ffmpeg.stdin.close()
        self._ffmpeg.wait()


class AgentOakPyBoy(PyBoy):
    """PyBoy that can show and record every frame.

    PyBoy's tick(count) runs count frames but renders only the last one and
    limits the speed once per call, so tools that tick many frames at once
    jump ahead in the window. With every_frame set, tick(count) runs count
    single rendered frames at the emulation speed instead.
    """

    every_frame: bool = False
    recorder: FrameRecorder | None = None

    def tick(self, count: int = 1, render: bool = True, sound: bool = True) -> bool:
        """Advance count frames, see PyBoy.tick."""
        if not self.every_frame:
            return super().tick(count, render, sound)
        running = True
        for _ in range(count):
            frame = self.frame_count
            running = super().tick(1, render, sound)
            # paused ticks don't advance the game, leave them out
            if self.recorder is not None and self.frame_count != frame:
                self.recorder.add_frame(self.screen.ndarray.tobytes())
            if not running:
                break
        return running

    def stop(self, save=True, ram_file=None, rtc_file=None) -> None:
        """Stop the emulator and finish the recording, see PyBoy.stop."""
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None
        super().stop(save, ram_file, rtc_file)


def create_emulator(
    rom_path: str,
    realtime: bool = False,
    record_path: Path | None = None,
) -> PyBoy:
    """Create a new emulator instance.

    Args:
        rom_path: The path to the ROM.
        realtime: Show every frame at real speed, also inside tool calls.
        record_path: Record every frame the game advances to this video file,
            implies realtime.
    Returns:
        The emulator instance.
    """
    pyboy = AgentOakPyBoy(
        rom_path,
        scale=1,
        debug=False,
        sound_emulated=True,
    )
    pyboy.every_frame = realtime or record_path is not None
    if record_path is not None:
        height, width = pyboy.screen.raw_buffer_dims
        pyboy.recorder = FrameRecorder(path=record_path, width=width, height=height)

    return pyboy


@contextmanager
def running(pyboy: PyBoy, mem_lock: Lock) -> Iterator[None]:
    """Let a paused emulator advance only for the duration of the block.

    In agent mode the emulator stays paused between tool calls, so the game
    does not drift while the LLM is thinking. If it is already running
    (manual mode, or unpaused with P), this only takes the lock.

    Args:
        pyboy: The emulator instance.
        mem_lock: A lock to synchronize access to the emulator's memory.
    """
    with mem_lock:
        was_paused = pyboy.paused
        if was_paused:
            # applied at the start of the next tick
            pyboy.send_input(WindowEvent.UNPAUSE)
        try:
            yield
        finally:
            if was_paused:
                pyboy.send_input(WindowEvent.PAUSE)
                # applies the pause without advancing a frame
                pyboy.tick()


def load_symbols(path: Path) -> dict[str, int]:
    """Load symbols from a file.

    Args:
        path: The path to the symbols file.
    Returns:
        A dictionary mapping symbol names to addresses.
    """
    syms = {}
    pat = re.compile(r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s+(\S+)")
    with path.open() as f:
        for line in f:
            m = pat.match(line)
            if m:
                bank, addr, name = m.groups()
                syms[name] = int(addr, 16)
    return syms


def grab_screen_png(pyboy: PyBoy, scale: int = 3) -> bytes | None:
    """Grab a screenshot of the emulator's current state as a PNG.

    Args:
        pyboy: The emulator instance to grab from.
        scale: The scale factor for the screenshot.
    Returns:
        A PNG image as bytes representing the emulator's screen.
    """
    if img := pyboy.screen.image:
        img = img.convert("RGB")
        if scale != 1:
            img = img.resize(
                size=(img.width * scale, img.height * scale),
                resample=0,
            )
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
