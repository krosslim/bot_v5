import secrets
import string

_ALPHABET = string.ascii_letters + string.digits  # A-Za-z0-9 = 62 символа

def gen_idk(length: int = 5) -> str:
    return ''.join(secrets.choice(_ALPHABET) for _ in range(length))
