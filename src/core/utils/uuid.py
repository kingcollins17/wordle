import uuid


def generate_uuid() -> str:
    """Generate a random UUID v4 string."""
    return str(uuid.uuid4())
