-- Migration: Add session_id column to lobbies table
-- This column stores the game session ID when a game is created from the lobby

ALTER TABLE `lobbies` 
ADD COLUMN `session_id` VARCHAR(255) DEFAULT NULL AFTER `code`;

-- Add index for faster lookups by session_id
CREATE INDEX `idx_session_id` ON `lobbies` (`session_id`);
