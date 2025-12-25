# WebSocket Handler Simplification

## Overview
Simplified the game WebSocket handler (`/ws/game/{game_id}`) by removing lobby waiting functionality. Users now signal their readiness via REST endpoints instead of through WebSocket lobby coordination.

## Important Changes

### **`start_game` Method Removed**
The `GameManager.start_game()` method has been **completely removed**. All game starts (including bot games) now use the `resume_game()` voting system:

- **Human vs Human**: Both players call `POST /game/resume/{game_id}` to start
- **Human vs Bot**: Both player and bot automatically vote via `resume_game()` to start immediately

This unifies the game start mechanism with the pause/resume system, making the codebase more consistent.

## Changes Made

### **Removed**
- ❌ `lobby_manager` dependency
- ❌ Lobby creation and player addition logic
- ❌ `WAITING` message type sending
- ❌ `lobby.ready.wait()` timeout logic
- ❌ `is_reconnecting` flag and conditional logic
- ❌ Lobby timeout handling

### **Simplified Flow**

#### **Old Flow (Removed)**
```
1. User connects to WebSocket
2. Check if game is waiting
3. Create/get lobby
4. Send WAITING message
5. Add player to lobby
6. Wait for lobby.ready event (with timeout)
7. Start game when both players ready
8. Send game state
9. Enter gameplay loop
```

#### **New Flow (Current)**
```
1. User connects to WebSocket
2. Validate user and game
3. Send current game state immediately
4. If bot game and waiting → auto-start
5. Enter gameplay loop (only active when in_progress)
```

## New WebSocket Handler Behavior

### **Connection Phase**
1. **Validate User**: Check if user exists
2. **Validate Game**: Check if game exists and player is in the game
3. **Handle Game Over**: Disconnect if game is already over
4. **Send Game State**: Always send current game state (waiting, in_progress, paused, etc.)

### **Bot Handling**
- If game is in `waiting` state AND opponent is a bot:
  - Reconnect the bot
  - Auto-start the game immediately
  - No waiting required

### **Gameplay Loop**
- Only active when `game.game_state == GameState.in_progress`
- Receives player guesses via WebSocket
- Handles bot turns automatically (2-10 second delay)
- Breaks when game state changes from `in_progress`

## How Players Signal Readiness

Players now use **REST endpoints** to signal they're ready to start:

### **Option 1: Use Resume Endpoint**
Since the game starts in `waiting` state (similar to `paused`), players can use the resume voting system:

```bash
# Player 1 signals ready
POST /game/resume/{game_id}
→ Response: { "data": false, "message": "Resume vote registered..." }

# Player 2 signals ready
POST /game/resume/{game_id}
→ Response: { "data": true, "message": "Game resumed successfully..." }
→ Game state changes to in_progress
→ Both players receive WebSocket broadcast
```

### **Option 2: Create Dedicated Start Endpoint** (Recommended)
You could create a new endpoint specifically for starting games:

```python
@game_router.post("/start/{game_id}", response_model=BaseResponse[bool])
async def start_game_endpoint(
    game_id: str,
    user: WordleUser = Depends(get_current_user),
    game_manager: GameManager = Depends(get_game_manager),
) -> BaseResponse[bool]:
    """
    Signal that a player is ready to start the game.
    Uses voting system - game starts when all players are ready.
    """
    # Similar to resume_game but for waiting state
    # Could reuse the resume_votes mechanism
```

## Benefits of Simplification

✅ **Clearer Separation of Concerns**: WebSocket handles real-time gameplay, REST handles state transitions  
✅ **Easier to Test**: No complex lobby coordination logic in WebSocket  
✅ **More Flexible**: Can add ready/unready toggles via REST without WebSocket changes  
✅ **Better Error Handling**: REST endpoints provide clear HTTP responses  
✅ **Reduced Complexity**: Removed ~80 lines of lobby coordination code  
✅ **Consistent Pattern**: Pause/Resume uses same pattern as Start (voting system)  

## Migration Notes

### **For Existing Clients**
Clients that previously connected to the WebSocket and waited for the game to start will need to:

1. Connect to WebSocket → Receive game state
2. If `game_state == "waiting"`:
   - Call `POST /game/resume/{game_id}` (or new start endpoint)
   - Wait for WebSocket broadcast with `game_state == "in_progress"`
3. Begin sending guesses

### **Example Client Flow**
```javascript
// Connect to WebSocket
const ws = new WebSocket(`ws://localhost:8000/game/ws/game/${gameId}?player_id=${playerId}`);

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  
  if (message.type === 'GAME_STATE') {
    const game = message.data;
    
    if (game.game_state === 'waiting') {
      // Signal ready via REST
      fetch(`/game/resume/${gameId}`, { method: 'POST' });
    } else if (game.game_state === 'in_progress') {
      // Start playing
      enableGameplay();
    }
  }
};
```

## Remaining WebSocket Functionality

The WebSocket still handles:
- ✅ Real-time game state updates
- ✅ Guess submission during gameplay
- ✅ Bot turn handling
- ✅ Connection management
- ✅ Broadcasting game events

## Next Steps

Consider creating a dedicated `/game/start/{game_id}` endpoint that:
- Works specifically for games in `waiting` state
- Uses the same voting mechanism as resume
- Provides clearer semantics than reusing the resume endpoint
