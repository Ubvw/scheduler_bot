"""
Shared session manager to avoid multiple instances.
"""
from session_manager import SessionManager

# Create a single shared instance
session_manager = SessionManager()
