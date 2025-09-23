import os
import firebase_admin
from firebase_admin import credentials

from src.core.env import get_environment_or_default

# Get current working directory
cwd = os.getcwd()

# Join with the filename
service_account_path = os.path.join(cwd, "serviceAccountKey.json")
environment = get_environment_or_default()
cred = credentials.Certificate(environment.get_firebase_config())
firebase_admin.initialize_app(cred)
