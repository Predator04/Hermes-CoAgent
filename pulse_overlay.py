import sys
import time
import tkinter as tk
from pathlib import Path


LOG_FILE = Path(__file__).with_name("pulse_debug.log")
SIZE = 36
TRANSPARENT = "#ff00ff"


def _log(message):
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def _arg(index, default):
    try:
        return int(sys.argv[index])
    except Exception:
        return default


def _hex_color(r, g, b):
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return f"#{r:02x}{g:02x}{b:02x}"


def main():
    x = _arg(1, 960)
    y = _arg(2, 540)
    color = _hex_color(_arg(3, 0), _arg(4, 255), _arg(5, 0))

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-toolwindow", True)
    except tk.TclError:
        pass
    try:
        root.attributes("-transparentcolor", TRANSPARENT)
    except tk.TclError:
        pass
    root.attributes("-alpha", 0.78)
    root.configure(bg=TRANSPARENT)
    root.geometry(f"{SIZE}x{SIZE}+{x - SIZE // 2}+{y - SIZE // 2}")

    canvas = tk.Canvas(
        root,
        width=SIZE,
        height=SIZE,
        highlightthickness=0,
        bd=0,
        bg=TRANSPARENT,
    )
    canvas.pack(fill="both", expand=True)
    canvas.create_oval(2, 2, SIZE - 2, SIZE - 2, fill=color, outline="#ffffff", width=2)

    frames = 10
    interval_ms = 30

    def fade(frame=0):
        alpha = max(0.0, 0.78 * (1.0 - frame / frames))
        try:
            root.attributes("-alpha", alpha)
        except tk.TclError:
            pass
        if frame >= frames:
            root.destroy()
            return
        root.after(interval_ms, fade, frame + 1)

    root.after(80, fade)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _log(f"Pulse overlay failed: {exc}")
