import socket
import time
from pathlib import Path

from django.db.backends.postgresql.base import DatabaseWrapper as PostgresDatabaseWrapper
from django.db.utils import OperationalError

try:
    from psycopg import OperationalError as PsycopgOperationalError
except Exception:  # pragma: no cover
    PsycopgOperationalError = OperationalError

_CONNECT_ERRORS = (OperationalError, PsycopgOperationalError, OSError)
_RETRY_DELAYS = (0.5, 1.5, 3.0, 5.0)
_CACHE_FILE = Path(__file__).resolve().parents[1] / ".neon_ipv4_cache"
_ip_cache = {}


def _read_disk_ip(host):
    try:
        stored_host, ip = _CACHE_FILE.read_text().strip().split(" ", 1)
        if stored_host == host and ip:
            return ip
    except Exception:
        return None
    return None


def _write_disk_ip(host, ip):
    try:
        _CACHE_FILE.write_text(f"{host} {ip}\n")
    except Exception:
        pass


def _lookup_ipv4(host):
    infos = socket.getaddrinfo(host, 5432, socket.AF_INET, socket.SOCK_STREAM)
    if not infos:
        return None
    return infos[0][4][0]


def _resolve_ipv4(host):
    if host in _ip_cache:
        return _ip_cache[host]
    last = None
    for attempt in range(3):
        try:
            ip = _lookup_ipv4(host)
            if ip:
                _ip_cache[host] = ip
                _write_disk_ip(host, ip)
                return ip
        except OSError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    disk = _read_disk_ip(host)
    if disk:
        _ip_cache[host] = disk
        return disk
    if last:
        raise last
    return None


def _with_hostaddr(conn_params):
    host = conn_params.get("host")
    if not host:
        return conn_params
    params = dict(conn_params)
    try:
        ip = _resolve_ipv4(host)
        if ip:
            params["hostaddr"] = ip
    except OSError:
        disk = _read_disk_ip(host)
        if disk:
            params["hostaddr"] = disk
    return params


class DatabaseWrapper(PostgresDatabaseWrapper):
    def get_new_connection(self, conn_params):
        last = None
        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                conn = super().get_new_connection(_with_hostaddr(conn_params))
                host = conn_params.get("host")
                ip = _ip_cache.get(host) or _read_disk_ip(host)
                if host and ip:
                    _write_disk_ip(host, ip)
                return conn
            except _CONNECT_ERRORS as exc:
                last = exc
                _ip_cache.pop(conn_params.get("host"), None)
                if attempt == len(_RETRY_DELAYS) - 1:
                    break
                time.sleep(delay)
        raise last
