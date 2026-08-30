import secrets
import string


def generate_room_code(length: int = 4) -> str:
    """Generate a random numeric room code string of specified length (default 4 digits)."""
    return "".join(secrets.choice(string.digits) for _ in range(length))
