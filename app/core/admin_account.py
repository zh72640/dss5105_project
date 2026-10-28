"""Built-in local administrator; only the salted password verifier is shipped."""

ADMIN_USERNAME = "admin"
ADMIN_ROLE = "admin"
# PBKDF2-HMAC-SHA256, 600,000 iterations; the plaintext is distributed privately.
ADMIN_PASSWORD_HASH = "8b08aa528cd881ce07ca026b641b39f5$221249f2b50efe2c6fe1930b065665eb8d36397acdb56b544004caac1b8e6fe3"


def ensure_regular_username(username):
    if isinstance(username, str) and username.casefold() == ADMIN_USERNAME:
        raise ValueError("The username admin is reserved for the built-in administrator. Choose another username.")
