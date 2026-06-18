"""
Hermes CoAgent - Security module
==================================
Token-based Bearer auth for CoAgent HTTP endpoints.

Usage:
  --secure            Generates a random 64-char hex token
  --token=KEY         Uses a specific token (or HERMES_COAGENT_TOKEN env var)

The @require_auth decorator wraps Flask route handlers.
Uses secrets.compare_digest() for timing-safe comparison.
"""
import os, sys, secrets, functools
from flask import request, jsonify

AUTH_TOKEN = None
AUTH_ENABLED = False

def init_auth(port=9123):
    global AUTH_TOKEN, AUTH_ENABLED
    token = None
    for arg in sys.argv:
        if arg.startswith('--token='):
            token = arg.split('=', 1)[1]
            break
    if not token:
        token = os.environ.get('HERMES_COAGENT_TOKEN', '')
    if '--secure' in sys.argv:
        if not token:
            token = secrets.token_hex(32)
        AUTH_ENABLED = True
        AUTH_TOKEN = token
        prefix = token[:16]
        suffix = token[-8:]
        print('[Auth] Secure mode enabled - token: ' + prefix + '...' + suffix)
        print('[Auth]   Use header: Authorization: Bearer ' + token)
        return
    if token:
        AUTH_ENABLED = True
        AUTH_TOKEN = token
        prefix = token[:16]
        suffix = token[-8:]
        print('[Auth] Token auth enabled - token: ' + prefix + '...' + suffix)
        return
    print('[Auth] WARNING: No authentication configured!')
    print('[Auth]   Your desktop is controllable by anyone on your network.')
    print('[Auth]   Pass --secure or --token=KEY to enable protection.')
    if port == 9123:
        print('[Auth]   Recommendation: use --secure to generate a random token.')

def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not AUTH_ENABLED:
            return f(*args, **kwargs)
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized - provide Bearer token'}), 401
        provided = auth_header[7:]
        if not secrets.compare_digest(provided, AUTH_TOKEN):
            return jsonify({'error': 'Invalid token'}), 403
        return f(*args, **kwargs)
    return wrapper

