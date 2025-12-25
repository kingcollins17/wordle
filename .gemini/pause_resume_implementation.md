# Pause/Resume Game Implementation Summary

## Overview
Implemented a voting-based pause/resume system for the Wordle game sessions. The system allows players to pause games and requires all players to vote before resuming.

## Changes Made

### 1. GameState Enum (`src/models/game_session.py`)
- **Added**: `paused = "paused"` state to the `GameState` enum
- This new state represents when a game is temporarily paused

### 2. GameSession Model (`src/models/game_session.py`)
- **Added**: `resume_votes: Set[str]` field to track player IDs who have voted to resume
- **Added**: `request_resume(player_id: str) -> bool` method
  - Adds a player's vote to resume the game
  - Automatically transitions game state to `in_progress` when all players vote
  - Clears resume votes after successful transition
  - Returns `True` if game resumed, `False` if still waiting for votes
- **Added**: `clear_resume_votes()` method
  - Clears all resume votes (used when pausing)

### 3. GameManager (`src/game/game_manager.py`)
- **Added**: `pause_game(session_id: str, player_id: str) -> bool` method
  - Validates the game exists and player is in the game
  - Only allows pausing games in `in_progress` state
  - Transitions game to `paused` state
  - Clears any existing resume votes
  - Broadcasts the new game state to all players
  - Returns `True` on success

- **Added**: `resume_game(session_id: str, player_id: str) -> bool` method
  - Validates the game exists and player is in the game
  - Only allows resuming games in `paused` state
  - Registers the player's vote to resume
  - Automatically resumes when all players vote
  - Broadcasts game state after each vote
  - Returns `True` if game resumed, `False` if waiting for more votes

## How It Works

### Pausing a Game
1. Any player in an active game can call `pause_game()`
2. The game state changes to `GameState.paused`
3. All players are notified via WebSocket broadcast
4. Resume votes are cleared

### Resuming a Game
1. Players call `resume_game()` to vote for resuming
2. Each vote is tracked in the `resume_votes` set
3. Game state is broadcast after each vote (showing current vote status)
4. When all players have voted:
   - Game state automatically changes to `GameState.in_progress`
   - Resume votes are cleared
   - All players are notified that the game has resumed

## Usage Example

```python
# Pause a game
await game_manager.pause_game(session_id="abc-123", player_id="player1")

# Player 1 votes to resume
resumed = await game_manager.resume_game(session_id="abc-123", player_id="player1")
# resumed = False (waiting for player 2)

# Player 2 votes to resume
resumed = await game_manager.resume_game(session_id="abc-123", player_id="player2")
# resumed = True (all players voted, game resumed)
```

## Broadcasting
Both `pause_game()` and `resume_game()` broadcast the game state using:
- Message Type: `MessageType.GAME_STATE`
- Data: The complete `GameSession` object

This ensures all players receive real-time updates about:
- When the game is paused
- Who has voted to resume
- When the game resumes

## Error Handling
Both methods raise `GameError` exceptions for:
- Non-existent game sessions
- Players not in the game
- Invalid state transitions (e.g., trying to pause a waiting game)

## REST API Endpoints

Two new endpoints have been added to `src/routes/game.py`:

### POST `/game/pause/{game_id}`
Pause an active game session.

**Authentication**: Required (uses `get_current_user` dependency)

**Path Parameters**:
- `game_id` (str): The session ID of the game to pause

**Response**: `BaseResponse[bool]`
- `data`: `True` if successfully paused
- `message`: "Game paused successfully"

**Error Responses**:
- `404`: Game not found
- `403`: User is not part of this game
- `400`: Game is not in a pausable state (e.g., already paused, waiting, or game over)
- `500`: Internal server error

**Example**:
```bash
curl -X POST "http://localhost:8000/game/pause/abc-123-def" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### POST `/game/resume/{game_id}`
Request to resume a paused game session using the voting system.

**Authentication**: Required (uses `get_current_user` dependency)

**Path Parameters**:
- `game_id` (str): The session ID of the game to resume

**Response**: `BaseResponse[bool]`
- `data`: `True` if game resumed (all players voted), `False` if waiting for more votes
- `message`: 
  - "Game resumed successfully - all players ready" (if resumed)
  - "Resume vote registered - waiting for other players" (if waiting)

**Error Responses**:
- `404`: Game not found
- `403`: User is not part of this game
- `400`: Game is not paused
- `500`: Internal server error

**Example**:
```bash
curl -X POST "http://localhost:8000/game/resume/abc-123-def" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Endpoint Flow Example

```
Player 1: POST /game/pause/{game_id}
→ Game state changes to "paused"
→ Both players receive WebSocket broadcast with paused state

Player 1: POST /game/resume/{game_id}
→ Response: { "data": false, "message": "Resume vote registered..." }
→ Both players receive WebSocket broadcast showing Player 1 has voted

Player 2: POST /game/resume/{game_id}
→ Response: { "data": true, "message": "Game resumed successfully..." }
→ Game state changes to "in_progress"
→ Both players receive WebSocket broadcast with resumed state
```

