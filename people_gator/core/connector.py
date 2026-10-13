import logging
import requests


logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    pass


def refresh_token(func):
    def wrapper(self, *args, **kwargs):
        response = func(self, *args, **kwargs)
        if response.status_code == 401:
            logger.info("Access token expired, refreshing token...")
            self.refresh()
            response = func(self, *args, **kwargs)

        return response

    return wrapper


class Connector:
    def __init__(self, username, password, login_route, refresh_route, scopes, login=True, user_agent="PeopleGator/1.0"):
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
        return self.session.get(url, params=params, stream=stream)

    @refresh_token
    def post(self, url, data=None, json=None, files=None, params=None):
        return self.session.post(url, data=data, json=json, files=files, params=params)

    @refresh_token
    def put(self, url, json=None, files=None):
        return self.session.put(url, json=json, files=files)

    @refresh_token
    def patch(self, url, json=None):
        return self.session.patch(url, json=json)

    @refresh_token
    def delete(self, url):
        return self.session.delete(url)

    def login(self):
        login_data = {
            "username": self.username,
            "password": self.password,
            "scope": " ".join(self.scopes)
        }

        response = self.session.post(self.login_route, data=login_data)

        if response.status_code != 200:
            raise AuthenticationError(f"Login failed with status code {response.status_code}: {response.text}")

        response_data = response.json()
        self.access_token = response_data.get("access_token")
        self.refresh_token = response_data.get("refresh_token")

        self.update_session_headers()

    def refresh(self):
        if not self.refresh_token:
            raise AuthenticationError("No refresh token available for refreshing access token.")

        refresh_data = {
            "refresh_token": self.refresh_token
        }

        response = self.session.post(self.refresh_route, data=refresh_data)

        if response.status_code != 200:
            raise AuthenticationError(f"Token refresh failed with status code {response.status_code}: {response.text}")

        response_data = response.json()
        self.access_token = response_data.get("access_token")
        self.refresh_token = response_data.get("refresh_token")

        self.update_session_headers()

    def update_session_headers(self):
        self.session.headers.update(self._get_headers())

    def _get_headers(self):
        return {
            **self._get_auth_header(),
            **self._get_accept_header(),
            **self._get_user_agent_header()
        }

    def _get_accept_header(self):
        return {'Accept': 'application/json'}

    def _get_auth_header(self):
        return {'Authorization': f'Bearer {self.access_token}'}

    def _get_user_agent_header(self):
        return {'User-Agent': self.user_agent}
