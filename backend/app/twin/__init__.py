"""Utilities digital twin: equipment catalog, telemetry engine, deterministic detectors and the agent workflow.

Telemetry comes from a labelled SIMULATED source until a real gateway pushes readings to /api/twin/ingest.
The agent only monitors, analyses, recommends, alerts and verifies. It has no way to operate equipment.
"""
