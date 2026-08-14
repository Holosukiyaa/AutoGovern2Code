from .app import hello


def public_hello(name: str) -> dict[str, str]:
    """The example's public response contract."""
    return hello(name)
