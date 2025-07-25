from enum import Enum
import string
import random
from pydantic import BaseModel, Field
from typing import List, Dict

from src.core.ai_service import AiService, WordDefinitionResponse


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
    async def ai_meaning(
        self, word: str, ai_service: AiService
    ) -> WordDefinitionResponse:
        """
        Mocked method to return the AI-generated meaning of a word.
        This should be replaced with an actual AI client integration.
        """
        word = word.upper()
        return await ai_service.get_word_definition(word)

    def reveal_letter(
        self, secret_word: str, already_revealed_indices: List[int]
    ) -> tuple[str, int]:
        """
        Reveal a random letter from the secret word that hasn't been revealed yet.
        Returns a tuple (letter, index).
        Raises ValueError if all letters have been revealed.
        """
        secret_word = secret_word.upper()
        unrevealed_indices = [
            i for i in range(len(secret_word)) if i not in already_revealed_indices
        ]

        if not unrevealed_indices:
            raise ValueError("All letters have already been revealed")

        index = random.choice(unrevealed_indices)
        return secret_word[index], index

    def fishout(self, secret_word: str, already_fished_out: List[str]) -> str:
        """
        Return a random letter that is NOT in the secret word and NOT in already_fished_out.
        Raises ValueError if no such letter is available.
        """
        secret_letters = set(secret_word.upper())
        all_letters = set(string.ascii_uppercase)
        excluded_letters = secret_letters.union(
            set(letter.upper() for letter in already_fished_out)
        )

        possible_letters = list(all_letters - excluded_letters)

        if not possible_letters:
            raise ValueError("No more letters to fish out")

        return random.choice(possible_letters)

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
