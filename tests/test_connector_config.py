"""Connection settings must work without editing application source."""
import json
from pathlib import Path

import pytest

from connectors.Connector import Connector


@pytest.fixture
def config_files(monkeypatch):
    read_text = Path.read_text
    exists = Path.exists
    for name in ['MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD']:
        monkeypatch.delenv(name, raising=False)
    def read(path, *args, **kwargs):
        if path.name == 'mysql_connection.json':
            return json.dumps({'host': 'config-host', 'port': 3306,
                               'database': 'config-db', 'user': 'config-user'})
        if path.name == 'mysql_connection.local.json':
            return json.dumps({'password': 'local-test-password'})
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    monkeypatch.setattr(Path, 'exists', lambda path: True if path.name == 'mysql_connection.local.json' else exists(path))


def test_shared_config_and_local_password_reach_mysql(config_files, monkeypatch):
    captured = {}
    def connect(**settings):
        captured.update(settings)
        return 'connection'
    monkeypatch.setattr('mysql.connector.connect', connect)
    assert Connector().connect() == 'connection'
    assert (captured['host'], captured['database'], captured['user']) == ('config-host', 'config-db', 'config-user')
    assert captured['password'] == 'local-test-password'


def test_environment_overrides_config_and_explicit_arguments_override_environment(config_files, monkeypatch):
    for key, value in {'HOST':'env-host', 'PORT':'3307', 'DATABASE':'env-db',
                       'USER':'env-user', 'PASSWORD':'env-test-password'}.items():
        monkeypatch.setenv('MYSQL_' + key, value)
    connection = Connector()
    assert (connection.server, connection.port, connection.database, connection.username, connection.password) == (
        'env-host', 3307, 'env-db', 'env-user', 'env-test-password')
    explicit = Connector('explicit-host', 3308, 'explicit-db', 'explicit-user', 'explicit-test-password')
    assert (explicit.server, explicit.port, explicit.database, explicit.username, explicit.password) == (
        'explicit-host', 3308, 'explicit-db', 'explicit-user', 'explicit-test-password')


def test_missing_password_fails_before_opening_connection(config_files, monkeypatch):
    exists = Path.exists
    monkeypatch.setattr(Path, 'exists', lambda path: False if path.name == 'mysql_connection.local.json' else exists(path))
    def forbidden(**settings):
        raise AssertionError('Missing configuration must fail before contacting MySQL')
    monkeypatch.setattr('mysql.connector.connect', forbidden)
    with pytest.raises(ValueError, match='MYSQL_PASSWORD'):
        Connector().connect()
