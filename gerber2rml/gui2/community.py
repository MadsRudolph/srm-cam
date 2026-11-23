"""The SRM-CAM Discord: asked once at launch, and always under Help.

Students help each other there, and new features are explained first, with
pictures. The launch invite shows once per INVITE_ROUND: raise it to ask
everyone again (someone who said "Not now" included).
"""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from gerber2rml.gui2 import dialogs, tier

DISCORD_URL = "https://discord.gg/JUVbzanj6B"
SEEN_KEY = "community/discord_invite_round"
INVITE_ROUND = 1


def open_discord(parent=None):
    """Open the invite in the browser, or show it when that fails."""
    if QDesktopServices.openUrl(QUrl(DISCORD_URL)):
        return True
    d = dialogs.Sheet(parent, "The Discord is on the web", width=520)
    d.say("A browser could not be opened from here. The invite is:")
    d.say(DISCORD_URL, mono=True)
    d.act("Close", kind="primary", on=d.accept, default=True)
    d.exec()
    return False


def should_invite(settings=None):
    settings = settings or tier._settings()
    try:
        return int(settings.value(SEEN_KEY, 0) or 0) < INVITE_ROUND
    except (TypeError, ValueError):
        return True


def maybe_invite(parent, settings=None, opener=None):
    """The launch invite. True if it was shown. Never asks twice a round."""
    settings = settings or tier._settings()
    if not should_invite(settings):
        return False
    d = dialogs.Sheet(parent, "Join the SRM-CAM Discord", width=540)
    d.say("Stuck on a board, the mill or the laser? Ask in #help: Mads and "
          "other students answer there.")
    d.say("New releases are announced and explained with pictures in "
          "#announcements, and you can show what you made, report a bug, "
          "or ask for a feature.")
    d.say("You can join later from Help ▸ Join the Discord.", small=True)
    d.setObjectName("discordInvite")
    out = {"go": False}

    def go():
        out["go"] = True
        d.accept()

    d.act("Not now", on=d.reject)
    d.act("Join the Discord", kind="primary", on=go, default=True)
    d.show()
    d.raise_()
    d.activateWindow()
    d.exec()
    settings.setValue(SEEN_KEY, INVITE_ROUND)
    if out["go"]:
        (opener or open_discord)(parent)
    return True
