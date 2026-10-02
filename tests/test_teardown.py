"""Closing the window must not lose the snippet that was just chosen.

Off Hyprland the window is an ordinary one, so destroying it fires
notify::is-active, which calls cancel() — re-entering the teardown.
"""


class FakeWindow:
    """Destroying it calls back, the way notify::is-active does on GNOME."""

    def __init__(self, picker):
        self.picker = picker
        self.destroyed = 0

    def destroy(self):
        self.destroyed += 1
        self.picker.on_active_changed(self, None)

    def is_active(self):
        return False


def picker(gtk, snippets):
    settings = {"config": {"mode": "normal", "filter": "both", "paste": "auto"},
                "filter": "both", "paste_options": [], "paste": "auto", "keys": "normal"}
    made = gtk.Picker(snippets, settings)
    made.was_active = True
    made.win = FakeWindow(made)
    return made


def test_a_chosen_snippet_survives_the_teardown(gtk):
    made = picker(gtk, [("Sig", "Best regards")])
    made.chosen = "Best regards"
    made.release()
    assert made.chosen == "Best regards"


def test_the_window_is_only_destroyed_once(gtk):
    made = picker(gtk, [("Sig", "Best regards")])
    window = made.win
    made.release()
    made.release()
    assert window.destroyed == 1


def test_cancelling_still_reports_nothing_chosen(gtk):
    made = picker(gtk, [("Sig", "Best regards")])
    made.cancel()
    assert made.chosen is None
