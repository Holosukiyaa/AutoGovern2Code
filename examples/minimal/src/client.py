from .api import public_hello


def greeting(name: str) -> str:
    return public_hello(name)["message"]
