import logger
import requests
import ipaddress
import math
import re
from urllib.parse import unquote

class IPCProtocolHandler:

    AUTH_HEADER = 'Authentication'
    DEFAULT_CONNECT_TIMEOUT = 3.05
    DEFAULT_READ_TIMEOUT = 15.0

    def __init__(self, host, port, path='/', password=None,
                 connect_timeout=DEFAULT_CONNECT_TIMEOUT,
                 read_timeout=DEFAULT_READ_TIMEOUT):
        self.log = logger.get_logger(__name__)
        safe_host = _validated_host(host)
        safe_port = _validated_port(port)
        safe_path = _normalized_path(path, 'path').rstrip('/')
        self.base_url = 'http://' + safe_host + ':' + safe_port + safe_path
        self.timeout = (
            _positive_timeout(connect_timeout),
            _positive_timeout(read_timeout),
        )
        self.headers = {
            'user-agent': 'ASFBot',
            'Accept': 'application/json',
        }
        if password:
            self.headers[self.AUTH_HEADER] = password
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.log.debug("ASF IPC client initialized")

    def get(self, resource, parameters=None):
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, dict):
            message = "\"parameters\" variable must be a dictionary"
            self.log.error(message)
            raise TypeError(message)
        return self._request('get', resource, params=parameters)

    def post(self, resource, payload=None):
        if payload is not None and not isinstance(payload, dict):
            message = "\"payload\" must be a dictionary"
            self.log.error(message)
            raise TypeError(message)
        return self._request('post', resource, json=payload)

    def _request(self, method, resource, **kwargs):
        url = self.base_url + _normalized_path(resource, 'resource')
        self.log.debug("Sending %s request to ASF IPC", method.upper())
        try:
            response = getattr(self.session, method)(
                url, timeout=self.timeout, allow_redirects=False, **kwargs
            )
            if 300 <= response.status_code < 400:
                return _failure(
                    self.log,
                    "ASF IPC returned HTTP {}.".format(response.status_code),
                )
            response.raise_for_status()
        except requests.Timeout:
            return _failure(self.log, "ASF IPC request timed out.")
        except requests.ConnectionError:
            return _failure(self.log, "Unable to connect to ASF IPC.")
        except requests.HTTPError as error:
            status = getattr(error.response, 'status_code', None)
            message = ("ASF IPC returned HTTP {}.".format(status)
                       if status is not None else "ASF IPC returned an HTTP error.")
            return _failure(self.log, message)
        except requests.RequestException:
            return _failure(self.log, "ASF IPC request failed.")

        try:
            return response.json()
        except (ValueError, requests.JSONDecodeError):
            return _failure(self.log, "ASF IPC returned invalid JSON.")


def _positive_timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("timeout must be a positive number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be a positive number")
    return float(value)


def _validated_host(host):
    if not isinstance(host, str):
        raise TypeError("host must be text")
    if not host or any(char.isspace() or ord(char) < 32 for char in host):
        raise ValueError("host must be a non-empty hostname or IP address")
    if any(char in host for char in '/\\?#@') or '://' in host:
        raise ValueError("host contains unsafe characters")
    if ':' in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError as error:
            raise ValueError("host must be a valid hostname or IP address") from error
        return '[' + host + ']'
    if len(host) > 253 or not re.fullmatch(r'[A-Za-z0-9_.-]+', host):
        raise ValueError("host must be a valid hostname or IP address")
    if re.fullmatch(r'[0-9.]+', host):
        try:
            ipaddress.IPv4Address(host)
        except ValueError as error:
            raise ValueError("host must be a valid hostname or IP address") from error
        return host
    labels = host.split('.')
    if any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-')
           for label in labels):
        raise ValueError("host must be a valid hostname or IP address")
    return host


def _validated_port(port):
    if isinstance(port, bool) or not isinstance(port, (str, int)):
        raise TypeError("port must be an integer from 1 to 65535")
    if isinstance(port, str) and not port.isdecimal():
        raise ValueError("port must be an integer from 1 to 65535")
    numeric_port = int(port)
    if not 1 <= numeric_port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535")
    return str(numeric_port)


def _normalized_path(value, field_name):
    if not isinstance(value, str):
        raise TypeError("{} must be text".format(field_name))
    if not value.startswith('/'):
        raise ValueError("{} must start with '/'".format(field_name))
    if any(char in value for char in '\\?#') or any(ord(char) < 32 for char in value):
        raise ValueError("{} contains unsafe characters".format(field_name))
    decoded = unquote(value)
    if (any(char in decoded for char in '\\?#')
            or any(ord(char) < 32 for char in decoded)
            or decoded.count('/') != value.count('/')):
        raise ValueError("{} contains unsafe encoded characters".format(field_name))
    parts = value.split('/')
    decoded_parts = decoded.split('/')
    if any(part in ('.', '..') for part in parts + decoded_parts):
        raise ValueError("{} contains unsafe traversal".format(field_name))
    trailing_slash = value.endswith('/')
    normalized = '/' + '/'.join(part for part in parts if part)
    if normalized != '/' and trailing_slash:
        normalized += '/'
    return normalized


def _failure(log, message):
    log.warning("ASF IPC request failed: %s", message)
    return {'Success': False, 'Message': message}
