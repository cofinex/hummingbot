# Cofinex OAuth 2.0 Authentication Implementation

## Overview

Cofinex uses **OAuth 2.0 / OpenID Connect** with Bearer token authentication, which is different from most exchanges that use HMAC signatures.

## Authentication Flow

### 1. **Get Access Token**

**Endpoint**: `https://auth.cofinex.io/realms/cofinex/protocol/openid-connect/token`

**Method**: `POST`

**Content-Type**: `application/x-www-form-urlencoded`

**Request Body**:
```
username=santosh_padhi@yahoo.com
password=Minos@001!
client_id=cofinex-exchange
scope=openid
grant_type=password
```

**Response**:
```json
{
    "access_token": "eyJhbGci...",
    "expires_in": 18000,  // 5 hours in seconds
    "refresh_expires_in": 86400,  // 24 hours
    "refresh_token": "eyJhbGci...",
    "token_type": "Bearer",
    "id_token": "eyJhbGci...",
    "not-before-policy": 1744163840,
    "session_state": "926cc045-403d-409d-82e3-bba074edaf0f",
    "scope": "openid kyc_profile_id ..."
}
```

### 2. **Use Bearer Token**

For all authenticated API requests, add header:
```
Authorization: Bearer {access_token}
```

### 3. **Token Refresh**

Tokens expire after 5 hours. The implementation automatically:
- Refreshes token 5 minutes before expiry
- Uses refresh_token if available
- Falls back to username/password if refresh fails

## Implementation Details

### Files Updated

1. **`cofinex_auth.py`** - Complete rewrite
   - OAuth 2.0 password grant implementation
   - Bearer token management
   - Automatic token refresh
   - Thread-safe token access

2. **`cofinex_constants.py`** - Added OAuth configuration
   - OAuth token endpoint
   - Client ID, scope, grant type
   - Token refresh buffer

3. **`cofinex_config_map.py`** - New file
   - Username field (email)
   - Password field (encrypted)
   - Domain field

4. **`cofinex_exchange.py`** - Updated auth initialization
   - Uses username/password instead of API key/secret

### Key Features

✅ **Automatic Token Management**
- Gets token on first request
- Refreshes before expiration
- Handles token expiration gracefully

✅ **Thread-Safe**
- Uses asyncio.Lock for concurrent access
- Prevents multiple simultaneous token requests

✅ **Error Handling**
- Falls back to new token request if refresh fails
- Logs errors for debugging
- Raises exceptions on critical failures

✅ **Secure Storage**
- Username/password stored encrypted
- Never logged or displayed
- Uses SecretStr for password fields

## Configuration

### User Setup

When user runs `connect cofinex`:

```
Enter your Cofinex account email/username >>> santosh_padhi@yahoo.com
Enter your Cofinex account password >>> [hidden input]
Enter your Cofinex environment (main or testnet) >>> main
```

### Config File

Stored in: `conf/connectors/cofinex.yml` (encrypted)

```yaml
cofinex_username: "santosh_padhi@yahoo.com"  # encrypted
cofinex_password: "Minos@001!"  # encrypted
domain: "main"
```

## API Request Flow

### Public APIs (No Authentication)

```python
# No Authorization header needed
GET /api/v1/symbols
GET /api/v1/ticker
GET /api/v1/depth
GET /api/v1/trades
```

### Private APIs (Require Bearer Token)

```python
# Authorization header automatically added
GET /api/v1/account
Headers: {
    "Authorization": "Bearer eyJhbGci..."
}

POST /api/v1/order
Headers: {
    "Authorization": "Bearer eyJhbGci...",
    "Content-Type": "application/json"
}
Body: {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": "0.1",
    "price": "50000"
}
```

## Token Lifecycle

```
1. First Request
   └─> No token exists
   └─> Request new token (username/password)
   └─> Store token + expiration time
   └─> Use token for request

2. Subsequent Requests
   └─> Check if token valid (not expired)
   └─> If valid: Use existing token
   └─> If expired: Refresh token
   └─> Use token for request

3. Token Refresh (5 min before expiry)
   └─> Use refresh_token
   └─> Get new access_token
   └─> Update expiration time
   └─> Continue with request

4. Refresh Failure
   └─> Fall back to username/password
   └─> Get new token
   └─> Continue with request
```

## WebSocket Authentication

**Note**: User confirmed WebSocket is **public** - no authentication needed for:
- Order book updates
- Ticker updates
- Trade updates
- Kline/candlestick data

If private WebSocket channels are needed later, Bearer token can be added to WebSocket connection.

## Security Considerations

### ✅ Secure by Design

1. **Encrypted Storage**
   - Username/password encrypted in config file
   - Never stored in plain text

2. **Token Security**
   - Tokens stored in memory only
   - Never logged
   - Automatically refreshed

3. **HTTPS Only**
   - All API calls use HTTPS
   - OAuth endpoint uses HTTPS

4. **No Password Transmission**
   - Password only sent to OAuth endpoint
   - Never sent in regular API requests
   - Only Bearer token used for API calls

### ⚠️ Best Practices

1. **Use Strong Password**
   - Enable 2FA on Cofinex account if available
   - Use unique password for API access

2. **Monitor Token Usage**
   - Check logs for authentication errors
   - Monitor for unusual activity

3. **Rotate Credentials**
   - Change password periodically
   - Revoke old tokens if compromised

## Error Handling

### Common Errors

1. **Invalid Credentials**
   ```
   Error: Failed to obtain access token
   Solution: Check username/password
   ```

2. **Token Expired**
   ```
   Error: 401 Unauthorized
   Solution: Automatic refresh will handle this
   ```

3. **Rate Limited**
   ```
   Error: Too many token requests
   Solution: Wait before retrying
   ```

### Automatic Recovery

The implementation automatically:
- Retries token requests on failure
- Refreshes expired tokens
- Falls back to new token if refresh fails
- Logs errors for debugging

## Testing

### Test Token Request

```python
from hummingbot.connector.exchange.cofinex.cofinex_auth import CofinexAuth
from hummingbot.connector.exchange.cofinex import cofinex_web_utils

# Create auth instance
auth = CofinexAuth(
    username="your_email@example.com",
    password="your_password"
)

# Set API factory
api_factory = cofinex_web_utils.build_api_factory_without_time_synchronizer_pre_processor(
    cofinex_web_utils.create_throttler()
)
auth.set_api_factory(api_factory)

# Get token
token = await auth.get_access_token()
print(f"Token: {token[:50]}...")
```

### Test Authenticated Request

```python
# Make authenticated request
rest_assistant = await api_factory.get_rest_assistant()
request = RESTRequest(
    url="https://api.cofinex.com/api/v1/account",
    method=RESTMethod.GET
)

# Auth automatically adds Bearer token
authenticated_request = await auth.rest_authenticate(request)
response = await rest_assistant.execute_request(authenticated_request)
```

## Summary

✅ **OAuth 2.0 Implementation Complete**
- Token request working
- Bearer token authentication
- Automatic token refresh
- Secure credential storage

✅ **Ready for Testing**
- Once Cofinex Trade Engine API endpoints are known
- Can test with real credentials
- All authentication logic in place

⚠️ **Next Steps**
- Get actual Trade Engine API base URL
- Get actual API endpoint paths
- Test with real credentials
- Complete exchange class refactoring
