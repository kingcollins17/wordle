# Session ID Integration for Lobbies

## Overview
Added `session_id` column to the `lobbies` table to track which game session was created from each lobby. This allows for better tracking and potential reconnection logic.

## Changes Made

### 1. Database Migration
**File:** `/src/database/add_session_id_to_lobbies.sql`
- Created new migration file to add `session_id` VARCHAR(255) column to the `lobbies` table
- Added index on `session_id` for faster lookups
- Column is nullable and defaults to NULL (lobbies without a game session yet)

### 2. Database Model
**File:** `/src/models/lobby.py`
- Added `session_id` field to `DatabaseLobby` model
- Field is Optional[str] with max_length=255
- Positioned after `code` field for logical grouping

### 3. API Endpoints
**File:** `/src/routes/lobbies.py`
- Updated `join_lobby` endpoint to store `session_id` when a game is created
- When P2 joins and game session is created, the lobby is updated with the session_id
- Lobby data is refreshed after update to include the session_id in the response

### 4. Repository
**File:** `/src/repositories/lobbies_repository.py`
- No changes needed - the generic update methods already support the new field

## API Response Changes

### GET /lobbies/{code}
The response now includes `session_id` in the lobby object:
```json
{
  "message": "Lobby found",
  "data": {
    "id": 1,
    "code": "ABCD",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",  // NEW
    "p1_id": 123,
    "p2_id": 456,
    ...
  }
}
```

### POST /lobbies/join
The response includes both the standalone `session_id` field and the full lobby object with `session_id`:
```json
{
  "message": "Lobby joined successfully",
  "data": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "lobby": {
      "id": 1,
      "code": "ABCD",
      "session_id": "550e8400-e29b-41d4-a716-446655440000",  // NEW
      "p1_id": 123,
      "p2_id": 456,
      ...
    },
    "is_host": false,
    "is_ready": true
  }
}
```

## Migration Instructions

To apply the migration, run:
```sql
SOURCE /Users/zidepeople/Development/wordle-backend/src/database/add_session_id_to_lobbies.sql;
```

Or execute the SQL directly:
```bash
mysql -u your_user -p your_database < src/database/add_session_id_to_lobbies.sql
```

## Workflow

1. **P1 creates lobby**: `session_id` is NULL (no game created yet)
2. **P2 joins lobby**: Game session is created, `session_id` is set
3. **Clients can poll**: GET /lobbies/{code} to check if `session_id` is set
4. **When session_id is set**: Both players can connect to the game session

## Benefits

- **Better tracking**: Know which game session came from which lobby
- **Reconnection logic**: Can potentially use lobby code to find session_id if needed
- **Debugging**: Easier to trace game sessions back to their lobby origin
- **Future features**: Could implement lobby-based spectating or replay features
