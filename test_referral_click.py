import unittest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.base_response import BaseResponse
from src.core.env import Environment
from src.core.models.reward import Reward
from src.core.models.user import User
from src.core.repository import Repository, GetRepository
from src.core.services.reward_service import RewardService, get_reward_service
from src.core.env import get_env
from src.routes.auth import (
    auth_router,
    extract_referral_code_from_url,
    RecordReferralClickRequest,
)


class TestReferralClick(unittest.TestCase):
    def test_extract_referral_code_from_url(self):
        # 1. Standard query param 'referral_code'
        self.assertEqual(
            extract_referral_code_from_url("https://wordle.app/?referral_code=REF123"),
            "REF123",
        )
        # 2. Case variations
        self.assertEqual(
            extract_referral_code_from_url("https://wordle.app/?referralCode=ABC999"),
            "ABC999",
        )
        # 3. 'ref' param
        self.assertEqual(
            extract_referral_code_from_url("https://wordle.app/?ref=REF_TEST"),
            "REF_TEST",
        )
        # 4. 'code' param
        self.assertEqual(
            extract_referral_code_from_url("https://wordle.app/join?code=XYZ888&source=share"),
            "XYZ888",
        )
        # 5. Flutter web / hash routing url
        self.assertEqual(
            extract_referral_code_from_url("https://wordle.app/#/invite?referral_code=HASH777"),
            "HASH777",
        )
        # 6. URL without protocol scheme
        self.assertEqual(
            extract_referral_code_from_url("wordle.app?referral_code=NOSCHEME"),
            "NOSCHEME",
        )
        # 7. URL without referral params
        self.assertIsNone(extract_referral_code_from_url("https://wordle.app/home"))
        # 8. Empty / None
        self.assertIsNone(extract_referral_code_from_url(""))
        self.assertIsNone(extract_referral_code_from_url(None))

    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(auth_router)
        self.mock_repo = MagicMock(spec=Repository)
        self.mock_reward_service = MagicMock(spec=RewardService)
        self.custom_env = Environment(REFERRAL_BONUS_COINS=150)

        # Override dependencies
        self.app.dependency_overrides[GetRepository(User)] = lambda: self.mock_repo
        self.app.dependency_overrides[get_reward_service] = lambda: self.mock_reward_service
        self.app.dependency_overrides[get_env] = lambda: self.custom_env

        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def test_record_referral_click_with_code(self):
        mock_user = User(id="user_1", username="testuser", referral_code="CODE123", coins=500)
        self.mock_repo.get = AsyncMock(return_value=mock_user)

        dummy_reward = Reward(
            id="reward_1",
            user_id="user_1",
            coins=150,
            title="Referral Link Click",
            description="Reward for referral link click with code CODE123",
        )
        self.mock_reward_service.reward = AsyncMock(return_value=dummy_reward)

        response = self.client.post(
            "/users/record-referral-click",
            json={"referral_code": "CODE123"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["coins"], 150)
        self.assertEqual(data["data"]["user_id"], "user_1")

        # Verify reward_service.reward was called with env.REFERRAL_BONUS_COINS
        self.mock_reward_service.reward.assert_awaited_once_with(
            user_id="user_1",
            coins=150,
            title="Referral Link Click",
            description="Reward for referral link click with code CODE123",
        )

    def test_record_referral_click_with_url(self):
        mock_user = User(id="user_2", username="referrer", referral_code="URLREF99", coins=200)
        self.mock_repo.get = AsyncMock(return_value=mock_user)

        dummy_reward = Reward(
            id="reward_2",
            user_id="user_2",
            coins=150,
            title="Referral Link Click",
            description="Reward for referral link click with code URLREF99",
        )
        self.mock_reward_service.reward = AsyncMock(return_value=dummy_reward)

        response = self.client.post(
            "/users/record-referral-click",
            json={"referral_url": "https://wordle.app/invite?referral_code=URLREF99"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["user_id"], "user_2")
        self.assertEqual(data["data"]["coins"], 150)

    def test_record_referral_click_user_not_found(self):
        self.mock_repo.get = AsyncMock(return_value=None)

        response = self.client.post(
            "/users/record-referral-click",
            json={"referral_code": "NONEXISTENT"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Referral code not found")

    def test_record_referral_click_invalid_url_no_param(self):
        response = self.client.post(
            "/users/record-referral-click",
            json={"referral_url": "https://wordle.app/no_params"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Could not extract referral code", response.json()["detail"])

    def test_record_referral_click_missing_both(self):
        response = self.client.post(
            "/users/record-referral-click",
            json={},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Either referral_code or referral_url must be provided", response.json()["detail"])

    def test_record_referral_click_with_both_uses_code(self):
        mock_user = User(id="user_code", username="usercode", referral_code="CODE_WINS", coins=200)
        self.mock_repo.get = AsyncMock(return_value=mock_user)

        dummy_reward = Reward(id="reward_both", user_id="user_code", coins=150)
        self.mock_reward_service.reward = AsyncMock(return_value=dummy_reward)

        response = self.client.post(
            "/users/record-referral-click",
            json={
                "referral_code": "CODE_WINS",
                "referral_url": "https://wordle.app/?referral_code=URL_LOSES",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.mock_reward_service.reward.assert_awaited_once_with(
            user_id="user_code",
            coins=150,
            title="Referral Link Click",
            description="Reward for referral link click with code CODE_WINS",
        )

    def test_record_referral_click_aliases_payload(self):
        mock_user = User(id="user_alias", username="useralias", referral_code="ALIAS_CODE", coins=200)
        self.mock_repo.get = AsyncMock(return_value=mock_user)

        dummy_reward = Reward(id="reward_alias", user_id="user_alias", coins=150)
        self.mock_reward_service.reward = AsyncMock(return_value=dummy_reward)

        response = self.client.post(
            "/users/record-referral-click",
            json={"url": "https://wordle.app/?ref=ALIAS_CODE"},
        )
        self.assertEqual(response.status_code, 200)
        self.mock_reward_service.reward.assert_awaited_once_with(
            user_id="user_alias",
            coins=150,
            title="Referral Link Click",
            description="Reward for referral link click with code ALIAS_CODE",
        )

    def test_record_referral_click_alias_endpoint(self):
        mock_user = User(id="user_3", username="aliasuser", referral_code="ALIAS123", coins=100)
        self.mock_repo.get = AsyncMock(return_value=mock_user)
        dummy_reward = Reward(id="reward_3", user_id="user_3", coins=150)
        self.mock_reward_service.reward = AsyncMock(return_value=dummy_reward)

        response1 = self.client.post(
            "/users/referral-click",
            json={"referral_code": "ALIAS123"},
        )
        self.assertEqual(response1.status_code, 200)

        response2 = self.client.post(
            "/users/referral/click",
            json={"referral_code": "ALIAS123"},
        )
        self.assertEqual(response2.status_code, 200)


if __name__ == "__main__":
    unittest.main()
