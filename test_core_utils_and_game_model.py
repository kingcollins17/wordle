import unittest
from src.core.utils import generate_room_code
from src.core.models.game import Game


class TestCoreUtilsAndGameModel(unittest.TestCase):
    def test_generate_room_code_default_length(self):
        code = generate_room_code()
        self.assertEqual(len(code), 4)
        self.assertTrue(code.isdigit())

    def test_generate_room_code_custom_length(self):
        code = generate_room_code(6)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_game_model_powerup_columns(self):
        game = Game(player_1="user_123")
        self.assertEqual(game.player_1_fish_outs, [])
        self.assertEqual(game.player_2_fish_outs, [])
        self.assertEqual(game.player_1_reveal_letters, [])
        self.assertEqual(game.player_2_reveal_letters, [])
        self.assertEqual(game.player_1_meanings, [])
        self.assertEqual(game.player_2_meanings, [])

        # Verify mutation / population works
        game.player_1_fish_outs.append("a")
        game.player_1_reveal_letters.append({"letter": "b", "index": 2})
        game.player_1_meanings.append({"definition": "a sample meaning"})

        self.assertEqual(game.player_1_fish_outs, ["a"])
        self.assertEqual(game.player_1_reveal_letters, [{"letter": "b", "index": 2}])
        self.assertEqual(game.player_1_meanings, [{"definition": "a sample meaning"}])


if __name__ == "__main__":
    unittest.main()
