from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from config import (
    PASSWORD_HASHER_TIME_COST,
    PASSWORD_HASHER_MEMORY_COST,
    PASSWORD_HASHER_PARALLELISM,
)

# Global hasher instance
password_hasher = PasswordHasher(
    time_cost=PASSWORD_HASHER_TIME_COST,  # iterations (balance between security/speed)
    memory_cost=PASSWORD_HASHER_MEMORY_COST,  # memory usage (makes GPU attacks expensive)
    parallelism=PASSWORD_HASHER_PARALLELISM,  # CPU threads
)


# Hash password
def hash_password(password):
    return password_hasher.hash(password)


# Verify password
def verify_password(password, password_hash):
    try:
        password_hasher.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False
