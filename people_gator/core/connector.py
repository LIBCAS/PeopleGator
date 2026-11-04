import logging
import requests


logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """An unsuccessful login or access-token refresh."""
    pass


def refresh_token(func):
    """Wrap an HTTP operation to refresh authentication once after HTTP 401.

    Args:
        func: HTTP operation to wrap.

    Returns:
        A wrapper returning the final HTTP response.
    """
    def wrapper(self, *args, **kwargs):
        """Run the wrapped HTTP request, refreshing once on HTTP 401.

        Args:
            *args: Arguments forwarded to the delegated operation.
            **kwargs: Keyword arguments forwarded to the delegated operation.

        Returns:
            The original response, or the response after one authentication retry.
        """
        try:
            response = func(self, *args, **kwargs)
        except requests.RequestException as exc:
            logger.error("HTTP operation %s failed (%s)", func.__name__, type(exc).__name__)
            raise
        if response.status_code == 401:
            logger.info("Access token expired, refreshing token...")
            self.refresh()
            response = func(self, *args, **kwargs)

        return response

    return wrapper


class Connector:
    """Authenticated HTTP session with one token-refresh retry on HTTP 401.

    Attributes:
        session: requests session carrying the authentication headers.
        access_token: Current bearer token; keep private.
        refresh_token: Token used to renew authentication; keep private.
    """

    def __init__(self, username, password, login_route, refresh_route, scopes, login=True, user_agent="PeopleGator/1.0"):
        """Create an HTTP session and optionally authenticate immediately.

        Args:
            username: App authentication username.
            password: App authentication password.
            login_route: Token-login endpoint.
            refresh_route: Token-refresh endpoint.
            scopes: Requested authorization scopes.
            login: Whether to authenticate during construction; defaults to True.
            user_agent: HTTP User-Agent header value.

        Raises:
            AuthenticationError: If the requested initial login fails.
        """
        self.username = username
        self.password = password
        self.user_agent = user_agent

        self.session = requests.Session()
        self.login_route = login_route
        self.refresh_route = refresh_route
        self.scopes = scopes

        self.access_token = None
        self.refresh_token = None

        if login:
            self.login()

        self._logger = logging.getLogger(__name__)

    @refresh_token
    def get(self, url, params=None, stream=False):
        """Send a GET request and retry once after refreshing an expired token.

        Args:
            url: HTTP request URL.
            params: Optional query-parameter mapping.
            stream: Whether to stream the response; defaults to False.

        Returns:
            The final requests.Response, including unsuccessful HTTP statuses.
        """
        return self.session.get(url, params=params, stream=stream)

    @refresh_token
    def post(self, url, data=None, json=None, files=None, params=None):
        """Send a POST request and retry once after refreshing an expired token.

        Args:
            url: HTTP request URL.
            data: Optional form fields or raw request body.
            json: Optional JSON request payload.
            files: Optional multipart upload mapping.
            params: Optional query-parameter mapping.

        Returns:
            The final requests.Response, including unsuccessful HTTP statuses.
        """
        return self.session.post(url, data=data, json=json, files=files, params=params)

    @refresh_token
    def put(self, url, json=None, files=None):
        """Send a PUT request and retry once after refreshing an expired token.

        Args:
            url: HTTP request URL.
            json: Optional JSON request payload.
            files: Optional multipart upload mapping.

        Returns:
            The final requests.Response, including unsuccessful HTTP statuses.
        """
        return self.session.put(url, json=json, files=files)

    @refresh_token
    def patch(self, url, json=None):
        """Send a PATCH request and retry once after refreshing an expired token.

        Args:
            url: HTTP request URL.
            json: Optional JSON request payload.

        Returns:
            The final requests.Response, including unsuccessful HTTP statuses.
        """
        return self.session.patch(url, json=json)

    @refresh_token
    def delete(self, url):
        """Send a DELETE request and retry once after refreshing an expired token.

        Args:
            url: HTTP request URL.

        Returns:
            The final requests.Response, including unsuccessful HTTP statuses.
        """
        return self.session.delete(url)

    def login(self):
        """Authenticate and update the session with the returned tokens.

        Raises:
            AuthenticationError: If authentication fails or a refresh token is missing.
        """
        login_data = {
            "username": self.username,
            "password": self.password,
            "scope": " ".join(self.scopes)
        }

        response = self.session.post(self.login_route, data=login_data)

        if response.status_code != 200:
            logger.error("Authentication request failed (HTTP %s)", response.status_code)
            raise AuthenticationError(f"Login failed with status code {response.status_code}: {response.text}")

        response_data = response.json()
        self.access_token = response_data.get("access_token")
        self.refresh_token = response_data.get("refresh_token")

        self.update_session_headers()

    def refresh(self):
        """Refresh tokens and update the session authentication headers.

        Raises:
            AuthenticationError: If authentication fails or a refresh token is missing.
        """
        if not self.refresh_token:
            logger.error("Cannot refresh authentication: no refresh token available")
            raise AuthenticationError("No refresh token available for refreshing access token.")

        refresh_data = {
            "refresh_token": self.refresh_token
        }

        response = self.session.post(self.refresh_route, data=refresh_data)

        if response.status_code != 200:
            logger.error("Authentication request failed (HTTP %s)", response.status_code)
            raise AuthenticationError(f"Token refresh failed with status code {response.status_code}: {response.text}")

        response_data = response.json()
        self.access_token = response_data.get("access_token")
        self.refresh_token = response_data.get("refresh_token")

        self.update_session_headers()

    def update_session_headers(self):
        """Apply authentication, accepted media type, and user-agent headers."""
        self.session.headers.update(self._get_headers())

    def _get_headers(self):
        """Return the combined request headers for this session."""
        return {
            **self._get_auth_header(),
            **self._get_accept_header(),
            **self._get_user_agent_header()
        }

    def _get_accept_header(self):
        """Return the JSON Accept header."""
        return {'Accept': 'application/json'}

    def _get_auth_header(self):
        """Return the bearer-token Authorization header."""
        return {'Authorization': f'Bearer {self.access_token}'}

    def _get_user_agent_header(self):
        """Return the configured User-Agent header."""
        return {'User-Agent': self.user_agent}
