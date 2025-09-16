import json
import re
import aiohttp
import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel
from fastapi import Depends, HTTPException

from src.core.env import Environment, get_env


# Response models for type safety
class Definition(BaseModel):
    part_of_speech: str
    meaning: str
    example: str


class WordDefinitionResponse(BaseModel):
    word: str
    valid: bool
    definitions: list[Definition]
    error: Optional[str] = None


class AiService:
    def __init__(self, api_key: str, api_url: str, model: str = "gemini-1.5-flash"):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.logger = logging.getLogger(__name__)

        # Game-specific banned words (extend as needed)
        self.banned_words = {
            "fuck",
            "shit",
            "damn",
            "hell",
            "bitch",
            "ass",
            "crap",
            # Add more offensive words as needed
        }

        # Compiled regex for validation
        self.word_pattern = re.compile(r"^[a-zA-Z]{3,12}$")

    def _create_mission_prompt(self, word: str) -> str:
        """Create the structured mission prompt for Gemini API."""
        return f"""You are a locked-down definition service for the 'Word Guesser' game. When activated via power-up, you will ONLY:

1. **Input/Output Protocol**
   * Accept: Single English words (3-12 letters) from game server
   * Return: JSON format with strict fields:
   ```json
   {{
     "word": "[requested_word]",
     "valid": boolean,
     "definitions": [
       {{
         "part_of_speech": string,
         "meaning": string (max 15 words),
         "example": string (max 12 words)
       }}
     ],
     "error": null|"invalid_word"|"not_in_dictionary"|"restricted"
   }}
   ```

2. **Definition Rules**
   * Provide **only 1 definition** (primary usage)
   * Maximum 15 words for meaning
   * Example sentence must use the word in game context (e.g., "They guessed the word 'quartz' correctly")

3. **Validation Checks**
   * `valid: false` if:
     * Word contains numbers/symbols
     * Not in English dictionary
     * Length <3 or >12 characters
   * `error: "restricted"` for:
     * Offensive words
     * Proper nouns

4. **Behavior Lock**
   * Never respond to non-word inputs
   * Never suggest variations or synonyms
   * No conversational replies - only the JSON structure

**Process this word: "{word}"**

Return ONLY the JSON response, no additional text."""

    def _validate_word(self, word: str) -> tuple[bool, Optional[str]]:
        """Validate the input word before sending to API."""
        if not word or not isinstance(word, str):
            return False, "invalid_word"

        # Check length and character constraints
        if not self.word_pattern.match(word):
            return False, "invalid_word"

        # Check for banned/offensive words
        if word.lower() in self.banned_words:
            return False, "restricted"

        return True, None

    async def get_word_definition(self, word: str) -> WordDefinitionResponse:
        """
        Get definition for a word using Gemini API.

        Args:
            word: The word to get definition for

        Returns:
            WordDefinitionResponse: Structured response with definition or error
        """
        try:
            # Pre-validation
            is_valid, error = self._validate_word(word)

            if not is_valid:
                return WordDefinitionResponse(
                    word=word,
                    valid=False,
                    definitions=[],
                    error=error,
                )

            # Prepare the API request
            prompt = self._create_mission_prompt(word)

            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,  # Low temperature for consistent responses
                    "maxOutputTokens": 300,
                    "topP": 0.8,
                    "topK": 10,
                },
            }

            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            }

            # Make API call
            async with aiohttp.ClientSession() as session:
                api_endpoint = f"{self.api_url}:generateContent"

                async with session.post(
                    api_endpoint,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:

                    if response.status != 200:
                        self.logger.error(f"Gemini API error: {response.status}")
                        raise HTTPException(
                            status_code=500, detail="AI service temporarily unavailable"
                        )

                    response_data = await response.json()

                    # Extract the generated text
                    if not response_data.get("candidates"):
                        raise ValueError("No response from AI model")

                    generated_text = response_data["candidates"][0]["content"]["parts"][
                        0
                    ]["text"]

                    # Parse the JSON response from Gemini
                    try:
                        # Clean the response (remove markdown code blocks if present)
                        cleaned_text = generated_text.strip()
                        if cleaned_text.startswith("```json"):
                            cleaned_text = cleaned_text[7:]
                        if cleaned_text.endswith("```"):
                            cleaned_text = cleaned_text[:-3]
                        cleaned_text = cleaned_text.strip()

                        ai_response = json.loads(cleaned_text)

                        # Validate the AI response structure
                        return WordDefinitionResponse(**ai_response)

                    except (json.JSONDecodeError, ValueError) as e:
                        self.logger.error(f"Failed to parse AI response: {e}")
                        # Fallback response
                        return WordDefinitionResponse(
                            word=word,
                            valid=False,
                            definitions=[],
                            error="not_in_dictionary",
                        )

        # except aiohttp.ClientTimeout:
        #     self.logger.error("Gemini API timeout")
        #     raise HTTPException(status_code=504, detail="AI service timeout")

        except aiohttp.ClientError as e:
            self.logger.error(f"Gemini API connection error: {e}")
            raise HTTPException(status_code=503, detail="AI service unavailable")

        except Exception as e:
            self.logger.error(f"Unexpected error in get_word_definition: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    async def health_check(self) -> bool:
        """
        Check if the AI service is healthy and responsive.

        Returns:
            bool: True if service is healthy, False otherwise
        """
        try:
            # Test with a simple word
            test_response = await self.get_word_definition("test")
            return isinstance(test_response, WordDefinitionResponse)
        except Exception:
            return False


# Example usage and configuration
def get_ai_service(env: Environment = Depends(get_env)) -> AiService:
    """Factory function to create AiService instance with environment variables."""
    import os
    from dotenv import load_dotenv

    api_key = env.gemini_api_key
    api_url = env.gemini_api_url
    model = env.gemini_api_model

    return AiService(api_key=api_key, api_url=api_url, model=model)
