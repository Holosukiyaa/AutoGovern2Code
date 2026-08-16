import unittest

from src.client import greeting


class HelloContractTests(unittest.TestCase):
    def test_client_interprets_public_response(self) -> None:
        self.assertEqual(greeting("AG2C"), "Hello, AG2C!")


if __name__ == "__main__":
    unittest.main()
