# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 7.x     | :white_check_mark: |
| < 7.0   | :x:                |

## Reporting a Vulnerability

Hermes CoAgent provides remote desktop control over your local network.
Security is a top priority.

**DO NOT** create a public GitHub issue for security vulnerabilities.

Instead, report via:
- **GitHub Security Advisories**: Use the "Report a vulnerability" link on the repo
- **Email**: security@example.com

You should receive a response within 48 hours. If not, follow up.

## Security Features

### Authentication
- Bearer token auth on all control endpoints
- `--secure` flag generates a random 64-char hex token
- Token persisted to `.token` file (gitignored, readable only by owner)
- Token can be regenerated via `POST /auth/token`

### CSRF Protection
- `GET /csrf-token` returns single-use CSRF tokens
- `@csrf_protect` decorator available for sensitive POST endpoints
- All browser-based auth already uses Bearer tokens (CSRF-safe)

### Input Sanitization
- Path traversal protection (`_sanitize_path`)
- Command injection prevention (`_sanitize_cmd`)
- Plugin names validated against strict regex

### Network Security
- CORS restricted to local origins by default
- Rate limiting (60 req/s per IP)
- Security headers enabled (X-Content-Type-Options, X-Frame-Options)
- Host header validation

## Deployment Recommendations

1. **Always use `--secure`** to enable auth
2. **Do not expose** CoAgent directly to the internet without a VPN or SSH tunnel
3. **Keep the `.token` file** safe — it controls access to your desktop
4. **Regularly regenerate** your auth token
5. **Review the action log** periodically for unexpected commands
