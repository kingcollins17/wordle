# Lobby Cleanup Worker

## Overview

The lobby cleanup worker is a background task that automatically deletes lobbies that have been inactive for more than 30 minutes. This helps keep the database clean and prevents stale lobbies from accumulating.

## Implementation

The worker uses **APScheduler** (Advanced Python Scheduler) to run periodic cleanup tasks. It's implemented in `src/workers/lobby_cleanup_worker.py`.

### Key Features

- **Automatic Cleanup**: Runs every 5 minutes by default
- **Configurable**: Both cleanup interval and lobby max age can be configured
- **Graceful Shutdown**: Properly shuts down during application shutdown
- **Logging**: Comprehensive logging for monitoring and debugging

### Configuration

The worker accepts the following configuration parameters:

- `cleanup_interval_minutes`: How often to run the cleanup job (default: 5 minutes)
- `lobby_max_age_minutes`: Maximum age of lobbies before deletion (default: 30 minutes)

### How It Works

1. The worker starts when the application starts (in the `lifespan` context manager)
2. Every 5 minutes, it queries all lobbies from the database
3. It checks each lobby's `created_at` timestamp
4. Lobbies older than 30 minutes are deleted
5. The worker logs how many lobbies were deleted

### Integration

The worker is integrated into the FastAPI application lifecycle in `src/app.py`:

```python
# Startup
await startup_lobby_cleanup_worker(
    db_manager=mysql_manager,
    cleanup_interval_minutes=5,  # Run every 5 minutes
    lobby_max_age_minutes=30,  # Delete lobbies older than 30 minutes
)

# Shutdown
await shutdown_lobby_cleanup_worker()
```

### Database Schema

The worker relies on the `created_at` field in the `lobbies` table:

```sql
CREATE TABLE lobbies (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(4) NOT NULL UNIQUE,
    -- ... other fields ...
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### Logging

The worker logs the following events:

- Worker startup with configuration
- Each cleanup job execution
- Number of lobbies deleted in each run
- Individual lobby deletions (with code and timestamp)
- Errors during cleanup

Example log output:

```
INFO: Lobby cleanup worker started. Running every 5 minutes, deleting lobbies older than 30 minutes.
INFO: Starting lobby cleanup job. Deleting lobbies created before 2025-12-22 13:10:59
INFO: Deleted old lobby: code=ABCD, created_at=2025-12-22 12:35:00, id=123
INFO: Lobby cleanup job completed. Deleted 3 old lobbies.
```

### Performance Considerations

- The worker fetches up to 1000 lobbies per run (configurable in the code)
- Lobbies are ordered by `created_at` (oldest first) for efficient early termination
- Once a lobby is found that's not old enough, the loop breaks early

### Dependencies

The worker requires the following Python package:

```
APScheduler==3.10.4
```

This has been added to `requirements.txt`.

### Future Enhancements

Potential improvements:

1. **Custom SQL Query**: Instead of fetching all lobbies and filtering in Python, use a SQL query with a WHERE clause for better performance
2. **Metrics**: Track cleanup statistics (e.g., total lobbies deleted over time)
3. **Configurable via Environment**: Make the intervals configurable via environment variables
4. **Notification**: Optionally notify users before their lobby is deleted
