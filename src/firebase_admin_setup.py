from src.core.env import APP_CONFIG
import logging
import firebase_admin
from firebase_admin import credentials
# from src.core.env import APP_CONFIG

logger = logging.getLogger(__name__)

def setup_firebase():

    try:
        env = APP_CONFIG
        cred_dict = env.get_firebase_config()
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin initialized successfully from service account JSON file.")
    except Exception as e:
        logger.warning(f"Firebase Admin initialization skipped or failed: {e}")
        raise e
