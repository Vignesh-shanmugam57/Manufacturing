class NotFoundError(Exception):
    """Raised by services when a resource does not exist or is not owned by the caller (-> HTTP 404)."""
