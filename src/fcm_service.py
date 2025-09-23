import logging
from typing import List, Dict, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum

from firebase_admin import messaging
from firebase_admin.exceptions import FirebaseError


class FCMErrorCode(Enum):
    """FCM error codes for better error handling."""

    INVALID_TOKEN = "invalid-registration-token"
    NOT_REGISTERED = "registration-token-not-registered"
    MESSAGE_RATE_EXCEEDED = "message-rate-exceeded"
    DEVICE_MESSAGE_RATE_EXCEEDED = "device-message-rate-exceeded"
    TOPICS_MESSAGE_RATE_EXCEEDED = "topics-message-rate-exceeded"
    INVALID_PACKAGE_NAME = "invalid-package-name"
    INVALID_PARAMETERS = "invalid-parameters"
    MESSAGE_TOO_BIG = "message-size-limit-exceeded"
    INVALID_DATA_KEY = "invalid-data-key"
    INVALID_TTL = "invalid-ttl"
    UNAVAILABLE = "unavailable"
    INTERNAL_ERROR = "internal-error"


@dataclass
class FCMResult:
    """Result of FCM operation."""

    success_count: int
    failure_count: int
    failed_tokens: List[str] = None
    errors: List[str] = None
    message_ids: List[str] = None

    def __post_init__(self):
        if self.failed_tokens is None:
            self.failed_tokens = []
        if self.errors is None:
            self.errors = []
        if self.message_ids is None:
            self.message_ids = []


class FCMService:
    """
    Production-ready Firebase Cloud Messaging service.

    Provides methods for sending push notifications to devices with proper
    error handling, logging, and batch processing capabilities.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize FCM service.

        Args:
            logger: Optional logger instance. If None, creates default logger.
        """
        self.logger = logger or self._setup_default_logger()
        self.max_batch_size = 500  # FCM batch limit
        self.max_multicast_size = 1000  # FCM multicast limit

    def _setup_default_logger(self) -> logging.Logger:
        """Setup default logger for FCM service."""
        logger = logging.getLogger(__name__)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def send_to_token(
        self,
        token: str,
        data: Optional[Dict[str, str]] = None,
        notification: Optional[messaging.Notification] = None,
        android_config: Optional[messaging.AndroidConfig] = None,
        apns_config: Optional[messaging.APNSConfig] = None,
        web_config: Optional[messaging.WebpushConfig] = None,
        dry_run: bool = False,
    ) -> Optional[str]:
        """
        Send a message to a single device.

        Args:
            token: Device registration token
            data: Optional data payload (key-value pairs)
            notification: Optional notification payload
            android_config: Optional Android-specific configuration
            apns_config: Optional APNS-specific configuration
            web_config: Optional web push configuration
            dry_run: If True, message will be validated but not sent

        Returns:
            Message ID if successful, None if failed

        Raises:
            ValueError: If token is empty or invalid format
            FirebaseError: If Firebase service error occurs
        """
        if not token or not isinstance(token, str):
            raise ValueError("Token must be a non-empty string")

        try:
            message = messaging.Message(
                data=data or {},
                notification=notification,
                android=android_config,
                apns=apns_config,
                webpush=web_config,
                token=token,
            )

            message_id = messaging.send(message, dry_run=dry_run)

            if dry_run:
                self.logger.info(
                    f"Message validated successfully for token: {token[:10]}..."
                )
            else:
                self.logger.info(f"Message sent successfully. ID: {message_id}")

            return message_id

        except FirebaseError as e:
            self.logger.error(f"Firebase error sending to token {token[:10]}...: {e}")
            if self._is_retriable_error(e):
                self.logger.warning(f"Error is retriable: {e.code}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error sending to token {token[:10]}...: {e}")
            raise

    def send_multicast(
        self,
        tokens: List[str],
        data: Optional[Dict[str, str]] = None,
        notification: Optional[messaging.Notification] = None,
        android_config: Optional[messaging.AndroidConfig] = None,
        apns_config: Optional[messaging.APNSConfig] = None,
        web_config: Optional[messaging.WebpushConfig] = None,
        dry_run: bool = False,
    ) -> FCMResult:
        """
        Send a message to multiple devices efficiently.

        Args:
            tokens: List of device registration tokens (max 1000)
            data: Optional data payload
            notification: Optional notification payload
            android_config: Optional Android-specific configuration
            apns_config: Optional APNS-specific configuration
            web_config: Optional web push configuration
            dry_run: If True, messages will be validated but not sent

        Returns:
            FCMResult with success/failure counts and failed tokens

        Raises:
            ValueError: If tokens list is empty or exceeds limit
            FirebaseError: If Firebase service error occurs
        """
        if not tokens:
            raise ValueError("Tokens list cannot be empty")

        if len(tokens) > self.max_multicast_size:
            raise ValueError(
                f"Too many tokens. Maximum allowed: {self.max_multicast_size}"
            )

        # Remove duplicates while preserving order
        unique_tokens = list(dict.fromkeys(tokens))
        if len(unique_tokens) != len(tokens):
            self.logger.warning(
                f"Removed {len(tokens) - len(unique_tokens)} duplicate tokens"
            )

        try:
            message = messaging.MulticastMessage(
                data=data or {},
                notification=notification,
                android=android_config,
                apns=apns_config,
                webpush=web_config,
                tokens=unique_tokens,
            )

            response = messaging.send_each_for_multicast(message, dry_run=dry_run)

            failed_tokens = []
            errors = []
            message_ids = []

            for idx, resp in enumerate(response.responses):
                if resp.success:
                    message_ids.append(resp.message_id)
                else:
                    failed_tokens.append(unique_tokens[idx])
                    error_msg = f"Token {unique_tokens[idx][:10]}...: {resp.exception}"
                    errors.append(error_msg)

                    if self._should_remove_token(resp.exception):
                        self.logger.warning(
                            f"Token should be removed: {unique_tokens[idx][:10]}..."
                        )

            result = FCMResult(
                success_count=response.success_count,
                failure_count=response.failure_count,
                failed_tokens=failed_tokens,
                errors=errors,
                message_ids=message_ids,
            )

            action = "validated" if dry_run else "sent"
            self.logger.info(
                f"Multicast {action}: {result.success_count} succeeded, "
                f"{result.failure_count} failed out of {len(unique_tokens)} tokens"
            )

            if result.failure_count > 0:
                self.logger.warning(f"Failed tokens count: {len(failed_tokens)}")

            return result

        except FirebaseError as e:
            self.logger.error(f"Firebase error in multicast: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in multicast: {e}")
            raise

    def send_batch(
        self, messages: List[messaging.Message], dry_run: bool = False
    ) -> FCMResult:
        """
        Send multiple messages in a batch (up to 500 messages).

        Each message can have different tokens, topics, or conditions.

        Args:
            messages: List of Message objects (max 500)
            dry_run: If True, messages will be validated but not sent

        Returns:
            FCMResult with success/failure information

        Raises:
            ValueError: If messages list is empty or exceeds limit
            FirebaseError: If Firebase service error occurs
        """
        if not messages:
            raise ValueError("Messages list cannot be empty")

        if len(messages) > self.max_batch_size:
            raise ValueError(
                f"Too many messages. Maximum allowed: {self.max_batch_size}"
            )

        try:
            response = messaging.send_each(messages, dry_run=dry_run)

            errors = []
            message_ids = []
            failed_count = 0

            for idx, resp in enumerate(response.responses):
                if resp.success:
                    message_ids.append(resp.message_id)
                else:
                    failed_count += 1
                    error_msg = f"Message {idx}: {resp.exception}"
                    errors.append(error_msg)

            result = FCMResult(
                success_count=response.success_count,
                failure_count=failed_count,
                errors=errors,
                message_ids=message_ids,
            )

            action = "validated" if dry_run else "sent"
            self.logger.info(
                f"Batch {action}: {result.success_count}/{len(messages)} messages succeeded"
            )

            if result.failure_count > 0:
                self.logger.warning(f"Batch failures: {result.failure_count}")

            return result

        except FirebaseError as e:
            self.logger.error(f"Firebase error in batch send: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in batch send: {e}")
            raise

    def send_to_topic(
        self,
        topic: str,
        data: Optional[Dict[str, str]] = None,
        notification: Optional[messaging.Notification] = None,
        android_config: Optional[messaging.AndroidConfig] = None,
        apns_config: Optional[messaging.APNSConfig] = None,
        web_config: Optional[messaging.WebpushConfig] = None,
        condition: Optional[str] = None,
        dry_run: bool = False,
    ) -> Optional[str]:
        """
        Send a message to a topic or topic condition.

        Args:
            topic: Topic name (ignored if condition is provided)
            data: Optional data payload
            notification: Optional notification payload
            android_config: Optional Android-specific configuration
            apns_config: Optional APNS-specific configuration
            web_config: Optional web push configuration
            condition: Optional condition for targeting (overrides topic)
            dry_run: If True, message will be validated but not sent

        Returns:
            Message ID if successful, None if failed

        Raises:
            ValueError: If both topic and condition are empty
            FirebaseError: If Firebase service error occurs
        """
        if not topic and not condition:
            raise ValueError("Either topic or condition must be provided")

        try:
            message = messaging.Message(
                data=data or {},
                notification=notification,
                android=android_config,
                apns=apns_config,
                webpush=web_config,
                topic=topic if not condition else None,
                condition=condition,
            )

            message_id = messaging.send(message, dry_run=dry_run)

            target = condition or f"topic:{topic}"
            action = "validated" if dry_run else "sent"
            self.logger.info(f"Message {action} to {target}. ID: {message_id}")

            return message_id

        except FirebaseError as e:
            target = condition or f"topic:{topic}"
            self.logger.error(f"Firebase error sending to {target}: {e}")
            raise
        except Exception as e:
            target = condition or f"topic:{topic}"
            self.logger.error(f"Unexpected error sending to {target}: {e}")
            raise

    def _is_retriable_error(self, error: FirebaseError) -> bool:
        """Check if error is retriable."""
        retriable_codes = {
            FCMErrorCode.MESSAGE_RATE_EXCEEDED.value,
            FCMErrorCode.DEVICE_MESSAGE_RATE_EXCEEDED.value,
            FCMErrorCode.TOPICS_MESSAGE_RATE_EXCEEDED.value,
            FCMErrorCode.UNAVAILABLE.value,
            FCMErrorCode.INTERNAL_ERROR.value,
        }
        return error.code in retriable_codes

    def _should_remove_token(self, error: Exception) -> bool:
        """Check if token should be removed from database."""
        if not isinstance(error, FirebaseError):
            return False

        removable_codes = {
            FCMErrorCode.INVALID_TOKEN.value,
            FCMErrorCode.NOT_REGISTERED.value,
        }
        return error.code in removable_codes

    def create_notification(
        self, title: str, body: str, image_url: Optional[str] = None
    ) -> messaging.Notification:
        """
        Create a notification object.

        Args:
            title: Notification title
            body: Notification body
            image_url: Optional image URL

        Returns:
            Notification object
        """
        return messaging.Notification(title=title, body=body, image=image_url)

    def create_android_config(
        self,
        priority: str = "high",
        ttl_seconds: Optional[int] = None,
        collapse_key: Optional[str] = None,
        notification_channel_id: Optional[str] = None,
    ) -> messaging.AndroidConfig:
        """
        Create Android-specific configuration.

        Args:
            priority: Message priority ("normal" or "high")
            ttl_seconds: Time to live in seconds
            collapse_key: Collapse key for message grouping
            notification_channel_id: Android notification channel ID

        Returns:
            AndroidConfig object
        """
        android_notification = None
        if notification_channel_id:
            android_notification = messaging.AndroidNotification(
                channel_id=notification_channel_id
            )

        return messaging.AndroidConfig(
            priority=priority,
            ttl=f"{ttl_seconds}s" if ttl_seconds else None,
            collapse_key=collapse_key,
            notification=android_notification,
        )
