import unittest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from starlette.websockets import WebSocketState

from src.game.websocket_manager import (
    WebSocketManager,
    CACHE_DURATION,
)


class TestWebSocketManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = WebSocketManager(cache_duration=timedelta(seconds=10))

    def _create_mock_websocket(self):
        ws = MagicMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        ws.close = AsyncMock()
        return ws

    async def test_send_preserves_message_id_and_caches_with_timestamp(self):
        mock_ws = self._create_mock_websocket()
        await self.manager.connect(mock_ws, "user_1")

        message_id = "msg_123"
        msg = {"id": message_id, "type": "game_update", "content": "hello"}

        success = await self.manager.send("user_1", msg)
        self.assertTrue(success)

        # Verify message["id"] is preserved
        self.assertEqual(msg.get("id"), message_id)

        # Verify websocket received text with id
        mock_ws.send_text.assert_called_once()
        sent_text = mock_ws.send_text.call_args[0][0]
        self.assertIn('"id": "msg_123"', sent_text)

        # Verify cached messages dictionary
        self.assertIn("user_1", self.manager.cached_messages)
        self.assertEqual(len(self.manager.cached_messages["user_1"]), 1)

        cached_entry = self.manager.cached_messages["user_1"][0]
        self.assertEqual(cached_entry["id"], message_id)
        self.assertIn("timestamp", cached_entry)
        self.assertIsInstance(cached_entry["timestamp"], datetime)

        # Verify message_cache alias references the same dictionary
        self.assertIs(self.manager.cached_messages, self.manager.message_cache)

    async def test_send_auto_assigns_uuid_if_id_is_none(self):
        mock_ws = self._create_mock_websocket()
        await self.manager.connect(mock_ws, "user_uuid")

        msg = {"type": "ping"}
        self.assertIsNone(msg.get("id"))

        success = await self.manager.send("user_uuid", msg)
        self.assertTrue(success)

        # Verify message["id"] is generated and attached
        self.assertIsNotNone(msg.get("id"))
        self.assertTrue(len(msg["id"]) > 0)
        self.assertEqual(self.manager.cached_messages["user_uuid"][0]["id"], msg["id"])

    async def test_remove_message_from_cache(self):
        mock_ws = self._create_mock_websocket()
        await self.manager.connect(mock_ws, "user_2")

        msg1 = {"id": "m1", "type": "chat", "text": "one"}
        msg2 = {"id": "m2", "type": "chat", "text": "two"}

        await self.manager.send("user_2", msg1)
        await self.manager.send("user_2", msg2)

        self.assertEqual(len(self.manager.cached_messages["user_2"]), 2)

        # Remove m1
        removed = self.manager.remove_message_from_cache("user_2", "m1")
        self.assertTrue(removed)
        self.assertEqual(len(self.manager.cached_messages["user_2"]), 1)
        self.assertEqual(self.manager.cached_messages["user_2"][0]["id"], "m2")

        # Try removing non-existent
        removed_again = self.manager.remove_message_from_cache("user_2", "m1")
        self.assertFalse(removed_again)

        # Also verify alias methods work
        removed_m2 = self.manager.remove_from_cache("user_2", "m2")
        self.assertTrue(removed_m2)
        self.assertEqual(len(self.manager.cached_messages["user_2"]), 0)

    async def test_clear_expired_messages(self):
        mock_ws = self._create_mock_websocket()
        await self.manager.connect(mock_ws, "user_3")

        msg_old = {"id": "old_id", "type": "old"}
        msg_new = {"id": "new_id", "type": "new"}

        await self.manager.send("user_3", msg_old)
        await self.manager.send("user_3", msg_new)

        # Artificially age the old message past CACHE_DURATION
        now = datetime.now()
        self.manager.cached_messages["user_3"][0]["timestamp"] = now - timedelta(seconds=100)
        self.manager.cached_messages["user_3"][1]["timestamp"] = now

        # Use cache duration of 10 seconds
        cleared = self.manager.clear_expired_messages(cache_duration=timedelta(seconds=10))
        self.assertEqual(cleared, 1)

        cached_remaining = self.manager.cached_messages["user_3"]
        self.assertEqual(len(cached_remaining), 1)
        self.assertEqual(cached_remaining[0]["id"], "new_id")

    async def test_periodic_cleanup_task(self):
        mock_ws = self._create_mock_websocket()
        await self.manager.connect(mock_ws, "user_4")

        msg = {"id": "t1", "type": "task_test"}
        await self.manager.send("user_4", msg)

        # Age it past duration
        self.manager.cached_messages["user_4"][0]["timestamp"] = datetime.now() - timedelta(seconds=20)

        # Start cleanup task with 0.05s interval and 10s duration
        task = self.manager.start_cleanup_task(
            interval_seconds=0.05,
            cache_duration=timedelta(seconds=10),
        )
        self.assertIsNotNone(task)
        self.assertFalse(task.done())

        # Let the loop tick so cleanup runs
        await asyncio.sleep(0.12)

        self.assertEqual(len(self.manager.cached_messages["user_4"]), 0)

        # Stop cleanup task
        await self.manager.stop_cleanup_task()
        self.assertIsNone(self.manager._cleanup_task)

    async def test_connect_forwards_most_recent_cached_message_without_recaching(self):
        uid = "user_5"
        mock_ws_1 = self._create_mock_websocket()
        await self.manager.connect(mock_ws_1, uid)

        msg1 = {"id": "m1", "type": "chat", "text": "message 1"}
        msg2 = {"id": "m2", "type": "chat", "text": "message 2"}

        await self.manager.send(uid, msg1)
        await self.manager.send(uid, msg2)

        # Disconnect user
        await self.manager.disconnect(uid, reason="Client closed")
        self.assertFalse(self.manager.is_connected(uid))
        self.assertEqual(len(self.manager.cached_messages[uid]), 2)

        # Reconnect with new websocket
        mock_ws_2 = self._create_mock_websocket()
        connect_success = await self.manager.connect(mock_ws_2, uid)
        self.assertTrue(connect_success)

        # Verify most recent message (msg2 / m2) was sent to the new connection
        mock_ws_2.send_text.assert_called_once()
        sent_text = mock_ws_2.send_text.call_args[0][0]
        self.assertIn('"id": "m2"', sent_text)
        self.assertIn('"text": "message 2"', sent_text)

        # Verify the message was NOT recached (still exactly 2 messages in cache)
        self.assertEqual(len(self.manager.cached_messages[uid]), 2)
        self.assertEqual(self.manager.cached_messages[uid][0]["id"], "m1")
        self.assertEqual(self.manager.cached_messages[uid][1]["id"], "m2")

        await self.manager.stop_cleanup_task()

    async def test_websocket_endpoint_removes_message_from_cache_on_ack(self):
        from src.routes.game import game_updates_websocket
        from fastapi import WebSocketDisconnect
        import json

        mock_ws = self._create_mock_websocket()
        mock_ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"id": "ack_msg_1", "status": "delivered"}),
            WebSocketDisconnect(),
        ])

        # Pre-populate cache with messages
        self.manager.cached_messages["user_endpoint"] = [
            {"id": "ack_msg_1", "text": "hello"},
            {"id": "keep_msg_2", "text": "world"},
        ]

        await game_updates_websocket(
            websocket=mock_ws,
            user_id="user_endpoint",
            ws_manager=self.manager,
        )

        # Verify ack_msg_1 was removed from cache
        remaining_ids = [m["id"] for m in self.manager.cached_messages.get("user_endpoint", [])]
        self.assertEqual(remaining_ids, ["keep_msg_2"])

    async def test_connect_does_not_forward_expired_message(self):
        uid = "user_expired_test"
        mock_ws_1 = self._create_mock_websocket()
        await self.manager.connect(mock_ws_1, uid)

        msg = {"id": "expired_msg", "type": "chat", "text": "too old"}
        await self.manager.send(uid, msg)

        # Disconnect user
        await self.manager.disconnect(uid)

        # Age the message beyond cache duration (cache_duration is 10s)
        self.manager.cached_messages[uid][0]["timestamp"] = datetime.now() - timedelta(seconds=30)

        # Reconnect with new websocket
        mock_ws_2 = self._create_mock_websocket()
        connect_success = await self.manager.connect(mock_ws_2, uid)
        self.assertTrue(connect_success)

        # Verify no message was forwarded because it was expired
        mock_ws_2.send_text.assert_not_called()

        await self.manager.stop_cleanup_task()

    async def test_make_guess_creates_matching_message_id_for_return_and_websocket(self):
        from src.game.game_manager import GameManager
        from src.core.models.game import Game, GameStatus, Player

        mock_ws_manager = MagicMock()
        mock_ws_manager.broadcast = AsyncMock()

        game = Game(
            id="game_1",
            status=GameStatus.IN_PROGRESS,
            current_turn=Player.p1,
            player_1="p1_user",
            player_2="p2_user",
            player_2_words=["APPLE"],
            player_1_words=["BERRY"],
            word_length=5,
            max_attempts=6,
            current_round=1,
            total_rounds=1,
        )

        game_repo = MagicMock()
        game_repo.get = AsyncMock(return_value=game)
        game_repo.update = AsyncMock()

        gm = GameManager(
            game_id="game_1",
            websocket_manager=mock_ws_manager,
            game_repo=game_repo,
            user_repo=MagicMock(),
            word_repo=MagicMock(),
        )

        event = await gm.make_guess(player_id="p1_user", guess="APPLY")

        # Verify returned event has an id
        self.assertIsNotNone(event.id)
        self.assertTrue(len(event.id) > 0)

        # Verify broadcast was called and its message payload has the exact same id
        mock_ws_manager.broadcast.assert_called_once()
        broadcast_data = mock_ws_manager.broadcast.call_args[0][0]
        self.assertEqual(broadcast_data["id"], event.id)

    async def test_use_powerup_creates_matching_message_id_for_return_and_websocket(self):
        from src.game.game_manager import GameManager
        from src.core.models.game import Game, GameStatus, Player
        from src.core.models.user import User
        from src.game.game_algorithm import PowerUpType

        mock_ws_manager = MagicMock()
        mock_ws_manager.broadcast = AsyncMock()

        game = Game(
            id="game_2",
            status=GameStatus.IN_PROGRESS,
            current_turn=Player.p1,
            player_1="p1_user",
            player_2="p2_user",
            player_2_words=["APPLE"],
            word_length=5,
            current_round=1,
            total_rounds=1,
        )

        user = User(id="p1_user", fish_out=3)

        game_repo = MagicMock()
        game_repo.get = AsyncMock(return_value=game)
        game_repo.update = AsyncMock()

        user_repo = MagicMock()
        user_repo.get = AsyncMock(return_value=user)
        user_repo.update = AsyncMock()

        gm = GameManager(
            game_id="game_2",
            websocket_manager=mock_ws_manager,
            game_repo=game_repo,
            user_repo=user_repo,
            word_repo=MagicMock(),
        )

        result = await gm.use_powerup(player_id="p1_user", powerup_type=PowerUpType.FISH_OUT)

        # Verify returned result has an id
        self.assertIsNotNone(result.id)
        self.assertTrue(len(result.id) > 0)

        # Verify broadcast was called and its message payload has the exact same id
        mock_ws_manager.broadcast.assert_called_once()
        broadcast_data = mock_ws_manager.broadcast.call_args[0][0]
        self.assertEqual(broadcast_data["id"], result.id)
        self.assertEqual(broadcast_data["payload"]["id"], result.id)


if __name__ == "__main__":
    unittest.main()
