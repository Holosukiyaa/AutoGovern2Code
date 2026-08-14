import unittest

from src.client import greeting


class HelloContractTests(unittest.TestCase):
    def test_client_interprets_public_response(self) -> None:
        self.assertEqual(greeting("DEG"), "Hello, DEG!")


if __name__ == "__main__":
    unittest.main()
