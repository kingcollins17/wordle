# Database-Managed Lobby System Implementation

## Summary

This implementation replaces the in-memory lobby management system with a database-managed lobby system. The new system stores lobby information in a MySQL database table and provides a RESTful API endpoint for lobby operations.

## Files Created

### 1. Database Migration (`src/database/migration.sql`)
- Creates the `lobbies` table with the following schema:
  - `id`: Auto-incrementing primary key
  - `code`: 4-character lobby code (unique)
  - `p1_id`: Player 1 user ID (foreign key to users.id)
  - `p2_id`: Player 2 user ID (foreign key to users.id)
  - `p1_device_id`: Player 1 device ID (for easier querying)
  - `p2_device_id`: Player 2 device ID (for easier querying)
  - `p1_words`: Comma-separated list of Player 1's words
  - `p2_words`: Comma-separated list of Player 2's words
  - `turn_time_limit`: Turn time limit in seconds (default: 120)
  - `word_length`: Length of words in the game
  - `rounds`: Number of rounds (equals length of words list)
  - `created_at`: Timestamp of lobby creation
  - `updated_at`: Timestamp of last update
- Includes foreign key constraints to users table
- Includes indexes for performance optimization (including device_id columns)

### 2. Database Model (`src/models/lobby.py`)
- `DatabaseLobby`: Pydantic model representing a lobby
- Helper methods:
  - `get_p1_words_list()`: Parse p1_words string into a list
  - `get_p2_words_list()`: Parse p2_words string into a list
  - `is_ready()`: Check if lobby is ready to start (both players joined)

### 3. Repository (`src/repositories/lobbies_repository.py`)
- `LobbiesRepository`: Data access layer for lobby operations
- Methods:
  - `get_lobby_by_code(code)`: Fetch lobby by code
  - `get_lobby_by_id(lobby_id)`: Fetch lobby by ID
  - `create_lobby(lobby_data)`: Create new lobby
  - `update_lobby(code, updates)`: Update lobby by code
  - `update_lobby_by_id(lobby_id, updates)`: Update lobby by ID
  - `delete_lobby(code)`: Delete lobby by code
  - `delete_lobby_by_id(lobby_id)`: Delete lobby by ID
  - `list_lobbies(...)`: List lobbies with filters and pagination
  - `get_user_active_lobby(user_id)`: Get user's active lobby by user_id
  - `get_user_active_lobby_by_device_id(device_id)`: Get user's active lobby by device_id
- Dependency injection function: `get_lobbies_repository()`

### 4. API Routes (`src/routes/lobbies.py`)
- **POST /lobbies/join**: Join or create a lobby
  - Request body:
    - `code`: 4-character lobby code
    - `words`: List of secret words
    - `turn_time_limit`: Optional turn time limit (only used by P1)
  - Behavior:
    - If lobby doesn't exist: Create new lobby with user as P1 (host)
    - If lobby exists and P1 is set but P2 is not: Join as P2 and create game
    - If lobby is full: Return error
  - Response:
    - `session_id`: Game session ID if lobby is ready, None if waiting for P2
    - `lobby`: Lobby information
    - `is_host`: Whether the user is the host (P1)
    - `is_ready`: Whether the lobby is ready to start

- **GET /lobbies/{code}**: Get lobby information
  - Returns lobby details by code

- **DELETE /lobbies/{code}**: Delete a lobby
  - Only the host (P1) can delete the lobby

## Files Modified

### 1. `src/models/__init__.py`
- Added export for `DatabaseLobby` model

### 2. `src/repositories/__init__.py`
- Added export for `LobbiesRepository`

### 3. `src/routes/__init__.py`
- Added export for `lobbies_router`

### 4. `src/app.py`
- Registered `lobbies_router` in the FastAPI app

## How It Works

### Creating a Lobby (Player 1)
1. User sends POST request to `/lobbies/join` with:
   - `code`: "ABCD"
   - `words`: ["HELLO", "WORLD"]
   - `turn_time_limit`: 120 (optional)
2. System creates new lobby with user as P1
3. Lobby settings are determined by P1's words:
   - `rounds`: 2 (length of words list)
   - `word_length`: 5 (length of each word)
4. Response includes `session_id: null` (waiting for P2)

### Joining a Lobby (Player 2)
1. User sends POST request to `/lobbies/join` with:
   - `code`: "ABCD"
   - `words`: ["APPLE", "GRAPE"]
2. System validates:
   - Words list length matches lobby rounds
   - Word length matches lobby word_length
3. System updates lobby with P2 data
4. System creates game session automatically
5. Response includes `session_id` of the created game

### Game Creation
When P2 joins, the system:
1. Fetches P1 and P2 user data
2. Creates a `GameSession` using `GameManager.create_game()`
3. Returns the `session_id` to both players
4. Players can then connect to the game via WebSocket

## Database Schema

```sql
CREATE TABLE `lobbies` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code` VARCHAR(4) NOT NULL,
  `p1_id` INT UNSIGNED DEFAULT NULL,
  `p2_id` INT UNSIGNED DEFAULT NULL,
  `p1_device_id` VARCHAR(255) DEFAULT NULL,
  `p2_device_id` VARCHAR(255) DEFAULT NULL,
  `p1_words` VARCHAR(2048) DEFAULT NULL,
  `p2_words` VARCHAR(2048) DEFAULT NULL,
  `turn_time_limit` INT UNSIGNED NOT NULL DEFAULT 120,
  `word_length` INT UNSIGNED NOT NULL,
  `rounds` INT UNSIGNED NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_code` (`code`),
  KEY `idx_p1_id` (`p1_id`),
  KEY `idx_p2_id` (`p2_id`),
  KEY `idx_p1_device_id` (`p1_device_id`),
  KEY `idx_p2_device_id` (`p2_device_id`),
  KEY `idx_code` (`code`),
  
  CONSTRAINT `fk_lobbies_p1_user` 
    FOREIGN KEY (`p1_id`) 
    REFERENCES `users` (`id`) 
    ON DELETE CASCADE 
    ON UPDATE CASCADE,
    
  CONSTRAINT `fk_lobbies_p2_user` 
    FOREIGN KEY (`p2_id`) 
    REFERENCES `users` (`id`) 
    ON DELETE CASCADE 
    ON UPDATE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;
```

## Next Steps

1. **Run the migration**: Execute the SQL in `src/database/migration.sql` to create the lobbies table
2. **Test the endpoint**: Use the POST `/lobbies/join` endpoint to create and join lobbies
3. **Optional cleanup**: Consider adding a cleanup job to delete old lobbies that were never completed
4. **Optional enhancement**: Add lobby expiration (e.g., delete lobbies older than 1 hour)

## Example Usage

### Create Lobby (P1)
```bash
POST /lobbies/join
{
  "code": "ABCD",
  "words": ["HELLO", "WORLD", "GAMES"],
  "turn_time_limit": 120
}

Response:
{
  "message": "Lobby created successfully",
  "data": {
    "session_id": null,
    "lobby": {
      "id": 1,
      "code": "ABCD",
      "p1_id": 123,
      "p2_id": null,
      "p1_words": "HELLO,WORLD,GAMES,",
      "p2_words": null,
      "turn_time_limit": 120,
      "word_length": 5,
      "rounds": 3,
      ...
    },
    "is_host": true,
    "is_ready": false
  }
}
```

### Join Lobby (P2)
```bash
POST /lobbies/join
{
  "code": "ABCD",
  "words": ["APPLE", "GRAPE", "LEMON"]
}

Response:
{
  "message": "Lobby joined successfully",
  "data": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "lobby": {
      "id": 1,
      "code": "ABCD",
      "p1_id": 123,
      "p2_id": 456,
      "p1_words": "HELLO,WORLD,GAMES,",
      "p2_words": "APPLE,GRAPE,LEMON,",
      "turn_time_limit": 120,
      "word_length": 5,
      "rounds": 3,
      ...
    },
    "is_host": false,
    "is_ready": true
  }
}
```
