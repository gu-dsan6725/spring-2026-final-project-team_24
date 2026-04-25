"""Canonical landscape node — MongoDB document.

Created when member concepts converge (similarity > threshold).
Holds perspectives array, merged edges, and item references.
Updated via delta operations ($push, $addToSet).
"""
