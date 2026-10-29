# Helix runbooks (example)

Credential stuffing on auth-api: enable rate limiting, block the source IPs at the WAF, force password resets for affected accounts.

Tier 1 service degraded: page the owner on-call within 5 minutes and open a P1 bridge.

Suspicious admin login: suspend the session, confirm with the user by phone, review audit logs for the last 24 hours.

Phishing domain reported: block it at the mail gateway and DNS, search mailboxes for the sender.
