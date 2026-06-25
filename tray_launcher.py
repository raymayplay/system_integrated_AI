import os
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def launch_assistant():
    script = ROOT / "pew.py"
    os.system(f'"{sys.executable}" "{script}"')


class TrayWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("HandleAI Tray")
        self.after(100, self.launch)

    def launch(self):
        launch_assistant()
        self.destroy()


if __name__ == "__main__":
    TrayWindow().mainloop()
