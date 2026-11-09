"""Python port of the Bailey JavaScript mechanics engine and bundled policy."""
# Public imports for scripts/notebooks. Importing the package does not create
# a population or open a window; construct BaileyEngine explicitly to start one.
from .config import default_config
from .engine import BaileyEngine
from .user_model import UserModel

__all__ = ["BaileyEngine", "UserModel", "default_config"]
