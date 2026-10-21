"""The walkthrough driven page by page offscreen, grabbing each page: the end-to-end proof and docs/screens use it.
authorize(user_code) plays the tester entering the device code (the stand-in's authorize)."""

from PySide6.QtWidgets import QApplication

from .app import grab
from .walkthrough import Walkthrough


def walkthrough(engine, out, folder, authorize, prefix="walkthrough-"):
    wizard = Walkthrough(engine, folder)
    wizard.show()
    saved = []

    def shot(name):
        saved.append(grab(wizard, out / f"{prefix}{name}.png"))

    shot("1-what")
    wizard.next()
    shot("2-sandbox")
    wizard.sandbox.read.setChecked(True)
    wizard.next()
    shot("3-when")
    wizard.next()
    shot("4-dumps")
    wizard.next()
    wizard.sign_in.start()
    shot("5-sign-in-code")
    authorize(wizard.sign_in.device["user_code"])
    wizard.sign_in.poll()
    shot("6-signed-in")
    wizard.next()
    wizard.register_page.register()
    shot("7-registered")
    wizard.next()
    shot("8-done")
    wizard.accept()
    QApplication.processEvents()
    return saved
