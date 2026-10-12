"""Shared rate limiter (slowapi), keyed by client IP.

Wired into the app in main.py; individual routes apply limits with
`@limiter.limit(...)`. Protects sensitive endpoints (login, signup) from
brute-force and abuse.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
