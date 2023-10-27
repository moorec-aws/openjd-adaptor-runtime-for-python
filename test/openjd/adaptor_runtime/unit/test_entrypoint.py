# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

from __future__ import annotations

import argparse
import json
import signal
from unittest.mock import ANY, MagicMock, Mock, PropertyMock, mock_open, patch

import jsonschema
import pytest
import yaml

import openjd.adaptor_runtime._entrypoint as runtime_entrypoint
from openjd.adaptor_runtime import EntryPoint
from openjd.adaptor_runtime.adaptors.configuration import (
    ConfigurationManager,
    RuntimeConfiguration,
)
from openjd.adaptor_runtime.adaptors import BaseAdaptor
from openjd.adaptor_runtime._background import BackendRunner, FrontendRunner
from openjd.adaptor_runtime._osname import OSName
from openjd.adaptor_runtime._entrypoint import _load_data

from .adaptors.fake_adaptor import FakeAdaptor
from .adaptors.configuration.stubs import AdaptorConfigurationStub, RuntimeConfigurationStub


@pytest.fixture(autouse=True)
def mock_configuration():
    with patch.object(
        ConfigurationManager, "build_config", return_value=RuntimeConfigurationStub()
    ):
        yield


@pytest.fixture(autouse=True)
def mock_logging():
    with (
        patch.object(
            BaseAdaptor,
            "config",
            new_callable=PropertyMock(return_value=AdaptorConfigurationStub()),
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_getLogger():
    with patch.object(runtime_entrypoint.logging, "getLogger"):
        yield


@pytest.fixture
def mock_adaptor_cls():
    mock_adaptor_cls = MagicMock()
    mock_adaptor_cls.return_value.config = AdaptorConfigurationStub()
    return mock_adaptor_cls


class TestStart:
    """
    Tests for the EntryPoint.start method
    """

    @patch.object(EntryPoint, "_parse_args")
    def test_creates_adaptor_with_init_data(
        self, _parse_args_mock: MagicMock, mock_adaptor_cls: MagicMock
    ):
        # GIVEN
        init_data = {"init": "data"}
        _parse_args_mock.return_value = argparse.Namespace(init_data=init_data)
        entrypoint = EntryPoint(mock_adaptor_cls)

        # WHEN
        entrypoint.start()

        # THEN
        _parse_args_mock.assert_called_once()
        mock_adaptor_cls.assert_called_once_with(init_data, path_mapping_data={})

    @patch.object(EntryPoint, "_parse_args")
    def test_creates_adaptor_with_path_mapping(
        self, _parse_args_mock: MagicMock, mock_adaptor_cls: MagicMock
    ):
        # GIVEN
        init_data = {"init": "data"}
        path_mapping_rules = {"path_mapping_rules": "data"}
        _parse_args_mock.return_value = argparse.Namespace(
            init_data=init_data, path_mapping_rules=path_mapping_rules
        )
        entrypoint = EntryPoint(mock_adaptor_cls)

        # WHEN
        entrypoint.start()

        # THEN
        _parse_args_mock.assert_called_once()
        mock_adaptor_cls.assert_called_once_with(init_data, path_mapping_data=path_mapping_rules)

    @patch.object(EntryPoint, "_parse_args")
    @patch.object(FakeAdaptor, "_cleanup")
    @patch.object(FakeAdaptor, "_start")
    def test_raises_adaptor_exception(
        self,
        mock_start: MagicMock,
        mock_cleanup: MagicMock,
        mock_parse_args: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        # GIVEN
        mock_start.side_effect = Exception()
        mock_parse_args.return_value = argparse.Namespace(command="run")
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        with pytest.raises(Exception) as raised_exc:
            entrypoint.start()

        # THEN
        assert raised_exc.value is mock_start.side_effect
        assert "Error running the adaptor: " in caplog.text
        mock_start.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch.object(EntryPoint, "_parse_args")
    @patch.object(FakeAdaptor, "_cleanup")
    @patch.object(FakeAdaptor, "_start")
    def test_raises_adaptor_cleanup_exception(
        self,
        mock_start: MagicMock,
        mock_cleanup: MagicMock,
        mock_parse_args: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        # GIVEN
        mock_start.side_effect = Exception()
        mock_cleanup.side_effect = Exception()
        mock_parse_args.return_value = argparse.Namespace(command="run")
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        with pytest.raises(Exception) as raised_exc:
            entrypoint.start()

        # THEN
        assert raised_exc.value is mock_cleanup.side_effect
        assert "Error running the adaptor: " in caplog.text
        assert "Error cleaning up the adaptor: " in caplog.text
        mock_start.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch.object(argparse.ArgumentParser, "parse_args")
    def test_raises_argparse_exception(
        self, mock_parse_args: MagicMock, caplog: pytest.LogCaptureFixture
    ):
        # GIVEN
        mock_parse_args.side_effect = Exception()
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        with pytest.raises(Exception) as raised_exc:
            entrypoint.start()

        # THEN
        assert raised_exc.value is mock_parse_args.side_effect
        assert "Error parsing command line arguments: " in caplog.text

    @patch.object(ConfigurationManager, "build_config")
    def test_raises_jsonschema_validation_err(
        self,
        mock_build_config: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        # GIVEN
        mock_build_config.side_effect = jsonschema.ValidationError("")
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        with pytest.raises(jsonschema.ValidationError) as raised_err:
            entrypoint.start()

        # THEN
        mock_build_config.assert_called_once()
        assert raised_err.value is mock_build_config.side_effect
        assert "Nonvalid runtime configuration file: " in caplog.text

    @patch.object(ConfigurationManager, "get_default_config")
    @patch.object(ConfigurationManager, "build_config")
    def test_uses_default_config_on_unsupported_system(
        self,
        mock_build_config: MagicMock,
        mock_get_default_config: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        # GIVEN
        mock_build_config.side_effect = NotImplementedError()
        mock_get_default_config.return_value = RuntimeConfigurationStub()
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        entrypoint.start()

        # THEN
        mock_build_config.assert_called_once()
        mock_get_default_config.assert_called_once()
        assert entrypoint.config is mock_get_default_config.return_value
        assert f"The current system ({OSName()}) is not supported for runtime "
        "configuration. Only the default configuration will be loaded. Full error: " in caplog.text

    @patch.object(EntryPoint, "_parse_args")
    @patch.object(ConfigurationManager, "build_config")
    @patch.object(RuntimeConfiguration, "config", new_callable=PropertyMock)
    @patch.object(runtime_entrypoint, "print")
    def test_shows_config(
        self,
        print_spy: MagicMock,
        mock_config: MagicMock,
        mock_build_config: MagicMock,
        mock_parse_args: MagicMock,
    ):
        # GIVEN
        config = {"key": "value"}
        mock_parse_args.return_value = argparse.Namespace(show_config=True)
        mock_config.return_value = config
        mock_build_config.return_value = RuntimeConfiguration({})
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        entrypoint.start()

        # THEN
        mock_parse_args.assert_called_once()
        mock_build_config.assert_called_once()
        mock_config.assert_called_once()
        print_spy.assert_called_once_with(yaml.dump(config, indent=2))

    @patch.object(EntryPoint, "_parse_args")
    def test_runs_in_run_mode(self, _parse_args_mock: MagicMock, mock_adaptor_cls: MagicMock):
        # GIVEN
        init_data = {"init": "data"}
        run_data = {"run": "data"}
        _parse_args_mock.return_value = argparse.Namespace(
            command="run",
            init_data=init_data,
            run_data=run_data,
        )
        entrypoint = EntryPoint(mock_adaptor_cls)

        # WHEN
        entrypoint.start()

        # THEN
        _parse_args_mock.assert_called_once()
        mock_adaptor_cls.assert_called_once_with(init_data, path_mapping_data=ANY)

        mock_adaptor_cls.return_value._start.assert_called_once()
        mock_adaptor_cls.return_value._run.assert_called_once_with(run_data)
        mock_adaptor_cls.return_value._stop.assert_called_once()
        mock_adaptor_cls.return_value._cleanup.assert_called_once()

    @patch.object(runtime_entrypoint, "AdaptorRunner")
    @patch.object(EntryPoint, "_parse_args")
    @patch.object(runtime_entrypoint.signal, "signal")
    def test_runmode_signal_hook(
        self,
        signal_mock: MagicMock,
        _parse_args_mock: MagicMock,
        mock_adaptor_runner: MagicMock,
        mock_adaptor_cls: MagicMock,
    ):
        # GIVEN
        init_data = {"init": "data"}
        run_data = {"run": "data"}
        _parse_args_mock.return_value = argparse.Namespace(
            command="run",
            init_data=init_data,
            run_data=run_data,
        )
        entrypoint = EntryPoint(mock_adaptor_cls)

        # WHEN
        entrypoint.start()
        entrypoint._sigint_handler(MagicMock(), MagicMock())

        # THEN
        signal_mock.assert_any_call(signal.SIGINT, entrypoint._sigint_handler)
        signal_mock.assert_any_call(signal.SIGTERM, entrypoint._sigint_handler)
        mock_adaptor_runner.return_value._cancel.assert_called_once()

    @patch.object(runtime_entrypoint, "InMemoryLogBuffer")
    @patch.object(runtime_entrypoint, "AdaptorRunner")
    @patch.object(EntryPoint, "_parse_args")
    @patch.object(BackendRunner, "run")
    @patch.object(BackendRunner, "__init__", return_value=None)
    def test_runs_background_serve(
        self,
        mock_init: MagicMock,
        mock_run: MagicMock,
        _parse_args_mock: MagicMock,
        mock_adaptor_runner: MagicMock,
        mock_log_buffer: MagicMock,
        mock_adaptor_cls: MagicMock,
    ):
        # GIVEN
        init_data = {"init": "data"}
        conn_file = "/path/to/conn_file"
        _parse_args_mock.return_value = argparse.Namespace(
            command="daemon",
            subcommand="_serve",
            init_data=init_data,
            connection_file=conn_file,
        )
        entrypoint = EntryPoint(mock_adaptor_cls)

        # WHEN
        entrypoint.start()

        # THEN
        _parse_args_mock.assert_called_once()
        mock_adaptor_cls.assert_called_once_with(init_data, path_mapping_data=ANY)
        mock_adaptor_runner.assert_called_once_with(
            adaptor=mock_adaptor_cls.return_value,
        )
        mock_init.assert_called_once_with(
            mock_adaptor_runner.return_value,
            conn_file,
            log_buffer=mock_log_buffer.return_value,
        )
        mock_run.assert_called_once()

    @patch.object(runtime_entrypoint, "AdaptorRunner")
    @patch.object(EntryPoint, "_parse_args")
    @patch.object(BackendRunner, "run")
    @patch.object(BackendRunner, "__init__", return_value=None)
    @patch.object(runtime_entrypoint.signal, "signal")
    def test_background_serve_no_signal_hook(
        self,
        signal_mock: MagicMock,
        mock_init: MagicMock,
        mock_run: MagicMock,
        _parse_args_mock: MagicMock,
        mock_adaptor_cls: MagicMock,
    ):
        # GIVEN
        init_data = {"init": "data"}
        conn_file = "/path/to/conn_file"
        _parse_args_mock.return_value = argparse.Namespace(
            command="daemon",
            subcommand="_serve",
            init_data=init_data,
            connection_file=conn_file,
        )
        entrypoint = EntryPoint(mock_adaptor_cls)

        # WHEN
        entrypoint.start()

        # THEN
        signal_mock.assert_not_called()

    @patch.object(EntryPoint, "_parse_args")
    @patch.object(FrontendRunner, "__init__", return_value=None)
    def test_background_start_raises_when_adaptor_module_not_loaded(
        self,
        mock_magic_init: MagicMock,
        _parse_args_mock: MagicMock,
    ):
        # GIVEN
        conn_file = "/path/to/conn_file"
        _parse_args_mock.return_value = argparse.Namespace(
            command="daemon",
            subcommand="start",
            connection_file=conn_file,
        )
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        with patch.dict(runtime_entrypoint.sys.modules, {FakeAdaptor.__module__: None}):
            with pytest.raises(ModuleNotFoundError) as raised_err:
                entrypoint.start()

        # THEN
        assert raised_err.match(f"Adaptor module is not loaded: {FakeAdaptor.__module__}")
        _parse_args_mock.assert_called_once()
        mock_magic_init.assert_called_once_with(conn_file)

    @patch.object(EntryPoint, "_parse_args")
    @patch.object(FrontendRunner, "__init__", return_value=None)
    @patch.object(FrontendRunner, "init")
    @patch.object(FrontendRunner, "start")
    def test_runs_background_start(
        self,
        mock_start: MagicMock,
        mock_magic_init: MagicMock,
        mock_magic_start: MagicMock,
        _parse_args_mock: MagicMock,
    ):
        # GIVEN
        conn_file = "/path/to/conn_file"
        _parse_args_mock.return_value = argparse.Namespace(
            command="daemon",
            subcommand="start",
            connection_file=conn_file,
        )
        mock_adaptor_module = Mock()
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        with patch.dict(
            runtime_entrypoint.sys.modules, {FakeAdaptor.__module__: mock_adaptor_module}
        ):
            entrypoint.start()

        # THEN
        _parse_args_mock.assert_called_once()
        mock_magic_init.assert_called_once_with(mock_adaptor_module, {}, {})
        mock_magic_start.assert_called_once_with(conn_file)
        mock_start.assert_called_once_with()

    @patch.object(EntryPoint, "_parse_args")
    @patch.object(FrontendRunner, "__init__", return_value=None)
    @patch.object(FrontendRunner, "shutdown")
    @patch.object(FrontendRunner, "stop")
    def test_runs_background_stop(
        self,
        mock_end: MagicMock,
        mock_shutdown: MagicMock,
        mock_magic_init: MagicMock,
        _parse_args_mock: MagicMock,
    ):
        # GIVEN
        conn_file = "/path/to/conn_file"
        _parse_args_mock.return_value = argparse.Namespace(
            command="daemon",
            subcommand="stop",
            connection_file=conn_file,
        )
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        entrypoint.start()

        # THEN
        _parse_args_mock.assert_called_once()
        mock_magic_init.assert_called_once_with(conn_file)
        mock_end.assert_called_once()
        mock_shutdown.assert_called_once_with()

    @patch.object(EntryPoint, "_parse_args")
    @patch.object(FrontendRunner, "__init__", return_value=None)
    @patch.object(FrontendRunner, "run")
    def test_runs_background_run(
        self,
        mock_run: MagicMock,
        mock_magic_init: MagicMock,
        _parse_args_mock: MagicMock,
    ):
        # GIVEN
        conn_file = "/path/to/conn_file"
        run_data = {"run": "data"}
        _parse_args_mock.return_value = argparse.Namespace(
            command="daemon",
            subcommand="run",
            connection_file=conn_file,
            run_data=run_data,
        )
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        entrypoint.start()

        # THEN
        _parse_args_mock.assert_called_once()
        mock_magic_init.assert_called_once_with(conn_file)
        mock_run.assert_called_once_with(run_data)

    @patch.object(EntryPoint, "_parse_args")
    @patch.object(FrontendRunner, "__init__", return_value=None)
    @patch.object(FrontendRunner, "run")
    @patch.object(runtime_entrypoint.signal, "signal")
    def test_background_no_signal_hook(
        self,
        signal_mock: MagicMock,
        mock_run: MagicMock,
        mock_magic_init: MagicMock,
        _parse_args_mock: MagicMock,
    ):
        # GIVEN
        conn_file = "/path/to/conn_file"
        run_data = {"run": "data"}
        _parse_args_mock.return_value = argparse.Namespace(
            command="daemon",
            subcommand="run",
            connection_file=conn_file,
            run_data=run_data,
        )
        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        entrypoint.start()

        # THEN
        signal_mock.assert_not_called()

    @patch.object(EntryPoint, "_parse_args")
    @patch.object(FrontendRunner, "__init__", return_value=None)
    def test_makes_connection_file_path_absolute(
        self,
        mock_init: MagicMock,
        _parse_args_mock: MagicMock,
    ):
        # GIVEN
        conn_file = "relpath"
        _parse_args_mock.return_value = argparse.Namespace(
            command="daemon",
            subcommand="",
            connection_file=conn_file,
        )

        entrypoint = EntryPoint(FakeAdaptor)

        # WHEN
        mock_isabs: MagicMock
        with (
            patch.object(runtime_entrypoint.os.path, "isabs", return_value=False) as mock_isabs,
            patch.object(runtime_entrypoint.os.path, "abspath") as mock_abspath,
        ):
            entrypoint.start()

        # THEN
        _parse_args_mock.assert_called_once()
        mock_isabs.assert_called_once_with(conn_file)
        mock_abspath.assert_called_once_with(conn_file)
        mock_init.assert_called_once_with(mock_abspath.return_value)


class TestLoadData:
    """
    Tests for the _load_data method
    """

    def test_defaults_to_dict(self):
        assert _load_data("") == {}

    @pytest.mark.parametrize(
        argnames=["input", "expected"],
        argvalues=[
            [json.dumps({"hello": "world"}), {"hello": "world"}],
            [yaml.dump({"hello": "world"}), {"hello": "world"}],
        ],
        ids=["JSON", "YAML"],
    )
    def test_accepts_string(self, input: str, expected: dict, caplog: pytest.LogCaptureFixture):
        # WHEN
        output = _load_data(input)

        # THEN
        assert output == expected

    @pytest.mark.parametrize(
        argnames=["input", "expected"],
        argvalues=[
            [json.dumps({"hello": "world"}), {"hello": "world"}],
            [yaml.dump({"hello": "world"}), {"hello": "world"}],
        ],
        ids=["JSON", "YAML"],
    )
    def test_accepts_file(self, input: str, expected: dict):
        # GIVEN
        filepath = "/my/file"
        file_uri = f"file://{filepath}"

        # WHEN
        open_mock: MagicMock
        with patch.object(runtime_entrypoint, "open", mock_open(read_data=input)) as open_mock:
            output = _load_data(file_uri)

        # THEN
        assert output == expected
        open_mock.assert_called_once_with(filepath)

    @patch.object(runtime_entrypoint, "open")
    def test_raises_on_os_error(self, mock_open: MagicMock, caplog: pytest.LogCaptureFixture):
        # GIVEN
        filepath = "/my/file.txt"
        file_uri = f"file://{filepath}"
        mock_open.side_effect = OSError()

        # WHEN
        with pytest.raises(OSError) as raised_err:
            _load_data(file_uri)

        # THEN
        assert raised_err.value is mock_open.side_effect
        mock_open.assert_called_once_with(filepath)
        assert "Failed to open data file: " in caplog.text

    def test_raises_when_parsing_fails(self, caplog: pytest.LogCaptureFixture):
        # GIVEN
        input = "@"

        # WHEN
        with pytest.raises(yaml.YAMLError):
            _load_data(input)

        # THEN
        assert "Failed to load data as JSON or YAML: " in caplog.text

    def test_raises_on_nonvalid_parsed_data_type(self):
        # GIVEN
        input = "input"

        # WHEN
        with pytest.raises(ValueError) as raised_err:
            _load_data(input)

        # THEN
        assert raised_err.match(f"Expected loaded data to be a dict, but got {type(input)}")