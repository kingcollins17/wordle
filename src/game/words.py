from .sixes_json import sixes_list
from .fives_json import fives_list
from .fours_json import fours_list


three_letter_words = [
    "cat",
    "dog",
    "sun",
    "hat",
    "map",
    "run",
    "box",
    "pen",
    "fun",
    "log",
]

four_letter_words = [i for i in fours_list if len(i) == 4]

five_letter_words = [i for i in fives_list if len(i) == 5]

six_letter_words = [i for i in sixes_list if len(i) == 6]
