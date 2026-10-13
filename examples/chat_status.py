"""
Minimal example: an orb next to a status line, as you would use it in a chat or AI tool.
Run:  python examples/chat_status.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from thinking_orbs import LABELS, ThinkingOrb

app = QApplication(sys.argv)
win = QWidget()
win.setWindowTitle("thinking-orbs example")
layout = QVBoxLayout(win)

# avatar-scale orb (64 px) next to a message
row = QHBoxLayout()
orb = ThinkingOrb(state="searching", size=64)   # theme="auto" follows the window palette
status = QLabel(LABELS["searching"])
row.addWidget(orb)
row.addWidget(status, 1)
layout.addLayout(row)

# inline-text orb (20 px) in front of a line of text
inline = QHBoxLayout()
inline.addWidget(ThinkingOrb(state="composing", size=20))
inline.addWidget(QLabel("Composing an answer…"), 1)
layout.addLayout(inline)

# cycle through a few agent steps, then stop
steps = iter(["connecting", "solving", "composing", "breathing"])


def next_step():
    state = next(steps, None)
    if state is None:
        orb.setPaused(True)
        status.setText("Done.")
        return
    orb.setState(state)
    status.setText(LABELS[state])


timer = QTimer(win)
timer.timeout.connect(next_step)
timer.start(2500)

win.resize(360, 140)
win.show()
sys.exit(app.exec())
