from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Dict


class LetterState(str, Enum):
    correct = "correct"
    misplaced = "misplaced"
    absent = "absent"


class LetterResult(BaseModel):
    letter: str
    state: LetterState


class GuessResult(BaseModel):
    letters: List[LetterResult]
    stats: Dict[LetterState, int] = Field(default_factory=dict)

    def is_correct(self):
        return self.stats[LetterState.correct] == len(self.letters)


class GameAlgorithm:

    def evaluate_guess(self, secret_word: str, guess: str) -> GuessResult:
        secret_word = secret_word.upper()
        guess = guess.upper()

        result = []
        secret_chars = list(secret_word)
        guess_chars = list(guess)

        # Track which positions in the secret word have been used
        used_secret_indices = set()

        # First pass: mark "correct" positions
        for i, (g_char, s_char) in enumerate(zip(guess_chars, secret_chars)):
            if g_char == s_char:
                result.append(LetterResult(letter=g_char, state=LetterState.correct))
                used_secret_indices.add(i)  # Mark this secret position as used
            else:
                result.append(None)  # placeholder
        # Second pass: mark "misplaced" and "absent"
        for i, g_char in enumerate(guess_chars):

            if result[i] is not None:  # Skip already processed (correct) letters
                continue

            found = False
            # Look for this letter in unused positions of the secret word
            for j, s_char in enumerate(secret_chars):
                if j not in used_secret_indices and g_char == s_char:
                    result[i] = LetterResult(letter=g_char, state=LetterState.misplaced)
                    used_secret_indices.add(j)  # Mark this secret position as used
                    found = True
                    break

            if not found:
                result[i] = LetterResult(letter=g_char, state=LetterState.absent)

        # Calculate stats
        stats = {
            LetterState.correct: 0,
            LetterState.misplaced: 0,
            LetterState.absent: 0,
        }
        for letter_result in result:
            stats[letter_result.state] += 1

        return GuessResult(letters=result, stats=stats)
