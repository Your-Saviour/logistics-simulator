"""Independent application identities; service scopes never imply operator rights."""
from dataclasses import dataclass
import secrets

PERMISSIONS = {
    'operator': frozenset({'status:read', 'jobs:write', 'runs:control', 'audit:read'}),
    'employee': frozenset({'status:read', 'jobs:write'}),
    'service': frozenset({'status:read', 'jobs:write'}),
}


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    scopes: frozenset[str]

    def public(self):
        return {'username': self.username, 'role': self.role, 'scopes': sorted(self.scopes)}


def accounts(settings):
    values = [{'username': settings.username, 'password': settings.password, 'role': 'operator'}, *settings.identities]
    seen = set()
    for entry in values:
        if entry.get('role') not in PERMISSIONS or not isinstance(entry.get('username'), str) or not entry['username'] or ':' in entry['username']:
            raise ValueError('Each identity needs a valid username and employee/operator/service role')
        if entry['username'] in seen or not isinstance(entry.get('password'), str) or not entry['password']:
            raise ValueError('Identity usernames must be unique and passwords nonempty')
        scopes = entry.get('scopes', PERMISSIONS[entry['role']] if entry['role'] != 'service' else ())
        if not isinstance(scopes, (list, tuple, set, frozenset)) or not set(scopes) <= PERMISSIONS[entry['role']]:
            raise ValueError('Identity permissions exceed the declared role')
        seen.add(entry['username'])
    return values


def identify(settings, username, password):
    found = None
    for account in accounts(settings):
        valid_user = secrets.compare_digest(username.encode(), account['username'].encode())
        valid_password = secrets.compare_digest(password.encode(), account['password'].encode())
        if valid_user and valid_password:
            role = account['role']
            found = Principal(username, role, frozenset(account.get('scopes', PERMISSIONS[role] if role != 'service' else ())))
    return found
