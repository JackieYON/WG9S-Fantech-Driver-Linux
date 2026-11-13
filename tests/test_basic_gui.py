import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest

from PySide6.QtCore import QEvent
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication

from kanata_basic import BasicWindow


class BasicGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_demo_edits_do_not_write(self):
        window = BasicWindow(demo=True)
        window.active.setCurrentIndex(2)
        self.assertEqual(window.draft()[1], 2)
        self.assertFalse(window.apply_button.isEnabled())
        window.apply_changes()
        self.assertEqual(window.trace, [])
        self.assertIsNone(window.job)

    def test_invalid_dpi_disables_apply(self):
        window = BasicWindow(demo=True)
        window.dpi[0].setValue(10050)
        self.assertIn("steps of 100", window.status.text())
        self.assertFalse(window.apply_button.isEnabled())

    def test_device_change_discards_old_settings(self):
        window = BasicWindow(demo=True)
        window.device_changed()
        self.assertIsNone(window.state)
        self.assertFalse(window.rate.isEnabled())
        self.assertFalse(window.apply_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
