# Error Handling & Exceptions

`folioman-client` provides a focused, predictable exception hierarchy derived from `FoliomanError`. This allows your application to handle missing entities, PDF password errors, parsing failures, and external price feed issues cleanly.

---

## Exception Hierarchy

```mermaid
graph TD
    Exception[Python Exception] --> FoliomanError[FoliomanError]
    FoliomanError --> FoliomanNotFoundError[FoliomanNotFoundError]
    FoliomanError --> FoliomanParseError[FoliomanParseError]
    FoliomanParseError --> FoliomanPasswordError[FoliomanPasswordError]
    FoliomanError --> FoliomanFeedError[FoliomanFeedError]
    FoliomanError --> FoliomanDatabaseError[FoliomanDatabaseError]
    FoliomanError --> FernetKeyUnavailable[FernetKeyUnavailable]
    FoliomanError --> FoliomanAuthError[FoliomanAuthError]
    FoliomanError --> FoliomanAPIError[FoliomanAPIError]
```

---

## Exception Classes

### `FoliomanError`

```python
class FoliomanError(Exception):
    """Base exception for all Folioman client errors."""
```

The common ancestor of all SDK exceptions. Catching `FoliomanError` intercepts any library-specific error.

---

### `FoliomanNotFoundError`

```python
class FoliomanNotFoundError(FoliomanError):
    """Raised when a requested resource (investor, security, transaction) does not exist."""
```

- **When Raised**:
    - Requesting an `investor_id` that is not present in the database.
    - Querying a `security_id` not found in the catalog.
- **Recommended Action**:
    - Catch and return a 404 or prompt the user to create the entity.

---

### `FoliomanParseError`

```python
class FoliomanParseError(FoliomanError):
    """Raised when statement parsing fails or document shape is unsupported."""
```

- **When Raised**:
    - The supplied file is not a valid CAMS/KFintech or NSDL/CDSL PDF statement.
    - The PDF structure is corrupted.

---

### `FoliomanPasswordError`

```python
class FoliomanPasswordError(FoliomanParseError):
    """Raised when the PDF password is wrong or missing."""
```

- **When Raised**:
    - Encrypted CAS PDF cannot be unlocked with the provided password.
- **Recommended Action**:
    - Prompt the user to re-enter their statement password (usually the investor's PAN).

---

### `FoliomanFeedError`

```python
class FoliomanFeedError(FoliomanError):
    """Raised when external price feed APIs fail or return malformed data."""
```

- **When Raised**:
    - Network timeout or HTTP 5xx errors from `mfapi.in`, AMFI, Yahoo Finance, or CoinGecko.
- **Recommended Action**:
    - Retain existing stale prices and retry the sync later.

---

### `FoliomanDatabaseError`

```python
class FoliomanDatabaseError(FoliomanError):
    """Raised on database connection failures or integrity constraint violations."""
```

- **When Raised**:
    - Database URL is unreachable or connection pool is exhausted.
    - Database integrity violation or unrecoverable SQL syntax error.

---

### `FernetKeyUnavailable`

```python
class FernetKeyUnavailable(FoliomanError):
    """Raised when no valid Fernet key can be resolved for PAN encryption."""
```

- **When Raised**:
    - The `FOLIOMAN_FERNET_KEY` is missing or invalid, and the local fallback key file (`~/.folioman/fernet.key`) cannot be read or created.
- **Recommended Action**:
    - Set `FOLIOMAN_FERNET_KEY` to a valid 32-byte URL-safe base64 string or check filesystem write permissions.

---

### `FoliomanAuthError`

```python
class FoliomanAuthError(FoliomanError):
    """Raised when authentication fails (invalid credentials, expired/rejected token refresh)."""
```

- **When Raised**:
    - Invalid username or password in legacy remote REST client mode.
    - Token refresh request fails or is rejected by remote server.

---

### `FoliomanAPIError`

```python
class FoliomanAPIError(FoliomanError):
    """Raised when the remote Folioman API returns an error response (HTTP 4xx/5xx)."""
```

- **Attributes**:
    - `status_code`: HTTP status code returned by the server (e.g. 400, 500).
    - `response_data`: Raw text or deserialized JSON response payload.
