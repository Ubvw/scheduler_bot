class SessionManager:
    """A simple in-memory session manager for the bot."""
    def __init__(self):
        # In-memory storage. Key: thread_id, Value: session data dict
        self._sessions = {}

    def create_session(self, channel_id: str, thread_ts: str) -> str:
        """Creates a new session, stores it, and returns its ID."""
        thread_id = f"{channel_id}:{thread_ts}"
        if thread_id in self._sessions:
            print(f"Warning: Session {thread_id} already exists. Overwriting.")
        
        self._sessions[thread_id] = {
            "thread_id": thread_id,
            "status": "running",  # Possible statuses: 'running', 'awaiting_hitl', 'completed'
        }
        print(f"Session created: {thread_id}")
        return thread_id

    def get_active_session(self, channel_id: str, thread_ts: str) -> dict | None:
        """Finds a session that is specifically awaiting HITL input."""
        thread_id = f"{channel_id}:{thread_ts}"
        session = self._sessions.get(thread_id)
        if session and session.get("status") == "awaiting_hitl":
            return session
        return None
    
    def get_any_session(self, channel_id: str, thread_ts: str) -> dict | None:
        """Finds any existing session for the thread, regardless of status."""
        thread_id = f"{channel_id}:{thread_ts}"
        return self._sessions.get(thread_id)

    def update_session_status(self, thread_id: str, status: str):
        """Updates the status of a session."""
        if thread_id in self._sessions:
            self._sessions[thread_id]["status"] = status
            print(f"Session {thread_id} status updated to: {status}")
        else:
            print(f"Error: Could not find session {thread_id} to update.")
    
    def session_exists(self, thread_id: str) -> bool:
        """Checks if a session exists."""
        return thread_id in self._sessions
            
    def close_session(self, thread_id: str):
        """Removes a session from active tracking once a workflow is complete."""
        if thread_id in self._sessions:
            del self._sessions[thread_id]
            print(f"Session {thread_id} closed.")