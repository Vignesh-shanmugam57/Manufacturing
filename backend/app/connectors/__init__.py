"""Connectors: read-only pulls from the plant's data applications into the app.

The app only ever reads. Every connection should use a read-only account; SQL is restricted to SELECT, web calls are
GET only, and passwords are stored encrypted and never returned to the browser.
"""
