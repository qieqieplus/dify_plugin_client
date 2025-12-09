import inspect
import json
import logging
from collections.abc import Callable, Generator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict
from yarl import URL

from ..entities.plugin_daemon import PluginDaemonBasicResponse, PluginDaemonError
from ..exceptions import (
    PluginDaemonBadRequestError,
    PluginDaemonInternalServerError,
    PluginDaemonNotFoundError,
    PluginDaemonUnauthorizedError,
    PluginInvokeError,
    PluginNotFoundError,
    PluginPermissionDeniedError,
    PluginUniqueIdentifierError,
    PluginDaemonInnerError,
)

T = TypeVar("T", bound=(BaseModel | dict[str, Any] | list[Any] | bool | str))

logger = logging.getLogger(__name__)

class PluginConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str = "http://localhost:5002"
    key: str = "plugin-api-key"
    timeout: float | httpx.Timeout | None = 300.0

class BasePluginClient:
    def __init__(self, config: PluginConfig):
        self.config = config
        self.base_url = URL(self.config.url)
        if isinstance(self.config.timeout, httpx.Timeout):
            self.timeout = self.config.timeout
        else:
            self.timeout = httpx.Timeout(self.config.timeout)

    def _request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        data: bytes | dict[str, Any] | str | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """
        Make a request to the plugin daemon inner API.
        """
        url, headers, prepared_data, params, files = self._prepare_request(path, headers, data, params, files)

        request_kwargs: dict[str, Any] = {
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "files": files,
            "timeout": self.timeout,
        }
        if isinstance(prepared_data, dict):
            request_kwargs["data"] = prepared_data
        elif prepared_data is not None:
            request_kwargs["content"] = prepared_data

        try:
            response = httpx.request(**request_kwargs)
        except httpx.RequestError:
            logger.exception("Request to Plugin Daemon Service failed")
            raise PluginDaemonInnerError(code=-500, message="Request to Plugin Daemon Service failed")

        return response

    def _prepare_request(
        self,
        path: str,
        headers: dict[str, str] | None,
        data: bytes | dict[str, Any] | str | None,
        params: dict[str, Any] | None,
        files: dict[str, Any] | None,
    ) -> tuple[str, dict[str, str], bytes | dict[str, Any] | str | None, dict[str, Any] | None, dict[str, Any] | None]:
        url = self.base_url / path
        prepared_headers = dict(headers or {})
        prepared_headers["X-Api-Key"] = self.config.key
        prepared_headers.setdefault("Accept-Encoding", "gzip, deflate, br")

        prepared_data: bytes | dict[str, Any] | str | None = (
            data if isinstance(data, (bytes, str, dict)) or data is None else None
        )
        if isinstance(data, dict):
            if prepared_headers.get("Content-Type") == "application/json":
                prepared_data = json.dumps(data)
            else:
                prepared_data = data

        return str(url), prepared_headers, prepared_data, params, files

    def _stream_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: bytes | dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Generator[str, None, None]:
        """
        Make a stream request to the plugin daemon inner API
        """
        url, headers, prepared_data, params, files = self._prepare_request(path, headers, data, params, files)

        stream_kwargs: dict[str, Any] = {
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "files": files,
            "timeout": self.timeout,
        }
        if isinstance(prepared_data, dict):
            stream_kwargs["data"] = prepared_data
        elif prepared_data is not None:
            stream_kwargs["content"] = prepared_data

        try:
            with httpx.stream(**stream_kwargs) as response:
                # Ensure HTTP errors are surfaced before consuming the stream
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    line = line.strip()
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line:
                        yield line
        except httpx.RequestError:
            logger.exception("Stream request to Plugin Daemon Service failed")
            raise PluginDaemonInnerError(code=-500, message="Request to Plugin Daemon Service failed")

    def _stream_request_with_model(
        self,
        method: str,
        path: str,
        type_: type[T],
        headers: dict[str, str] | None = None,
        data: bytes | dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Generator[T, None, None]:
        """
        Make a stream request to the plugin daemon inner API and yield the response as a model.
        """
        for line in self._stream_request(method, path, params, headers, data, files):
            yield type_(**json.loads(line))

    def _request_with_model(
        self,
        method: str,
        path: str,
        type_: type[T],
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> T:
        """
        Make a request to the plugin daemon inner API and return the response as a model.
        """
        response = self._request(method, path, headers, data, params, files)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.exception("Failed to request plugin daemon, status: %s, url: %s", e.response.status_code, path)
            raise

        try:
            return type_(**response.json())
        except Exception as exc:
            msg = f"Failed to parse response from plugin daemon to {type_.__name__}, url: {path}"
            logger.exception(msg)
            raise ValueError(msg) from exc

    def _request_with_plugin_daemon_response(
        self,
        method: str,
        path: str,
        type_: type[T],
        headers: dict[str, str] | None = None,
        data: bytes | dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        transformer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> T:
        """
        Make a request to the plugin daemon inner API and return the response as a model.
        """
        try:
            response = self._request(method, path, headers, data, params, files)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.exception("Failed to request plugin daemon, status: %s, url: %s", e.response.status_code, path)
            raise e
        except Exception as e:
            msg = f"Failed to request plugin daemon, url: {path}"
            logger.exception("Failed to request plugin daemon, url: %s", path)
            raise ValueError(msg) from e

        try:
            json_response = response.json()
            if transformer:
                json_response = transformer(json_response)
            rep = PluginDaemonBasicResponse[type_].model_validate(json_response)
        except Exception:
            msg = (
                f"Failed to parse response from plugin daemon to PluginDaemonBasicResponse [{str(type_.__name__)}],"
                f" url: {path}"
            )
            logger.exception(msg)
            raise ValueError(msg)

        if rep.code != 0:
            try:
                error = PluginDaemonError.model_validate(json.loads(rep.message))
            except Exception:
                raise ValueError(f"{rep.message}, code: {rep.code}")

            self._handle_plugin_daemon_error(error.error_type, error.message)
        if rep.data is None:
            frame = inspect.currentframe()
            raise ValueError(f"got empty data from plugin daemon: {frame.f_lineno if frame else 'unknown'}")

        return rep.data

    def _request_with_plugin_daemon_response_stream(
        self,
        method: str,
        path: str,
        type_: type[T],
        headers: dict[str, str] | None = None,
        data: bytes | dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Generator[T, None, None]:
        """
        Make a stream request to the plugin daemon inner API and yield the response as a model.
        """
        for line in self._stream_request(method, path, params, headers, data, files):
            try:
                rep = PluginDaemonBasicResponse[type_].model_validate_json(line)
            except (ValueError, TypeError):
                try:
                    line_data = json.loads(line)
                except (ValueError, TypeError):
                    raise ValueError(line)
                raise ValueError(line_data.get("error", line))

            if rep.code != 0:
                try:
                    error = PluginDaemonError.model_validate(json.loads(rep.message))
                    self._handle_plugin_daemon_error(error.error_type, error.message)
                except PluginDaemonInnerError:
                    raise
                except Exception:
                    if rep.code == -500:
                        raise PluginDaemonInnerError(code=rep.code, message=rep.message)
                    raise ValueError(f"plugin daemon: {rep.message}, code: {rep.code}")
            if rep.data is None:
                frame = inspect.currentframe()
                raise ValueError(f"got empty data from plugin daemon: {frame.f_lineno if frame else 'unknown'}")
            yield rep.data

    def _handle_plugin_daemon_error(self, error_type: str, message: str):
        """
        handle the error from plugin daemon
        """
        match error_type:
            case "PluginDaemonInnerError":
                raise PluginDaemonInnerError(code=-500, message=message)
            case "PluginInvokeError":
                raise PluginInvokeError(message)
            case "PluginDaemonInternalServerError":
                raise PluginDaemonInternalServerError(message)
            case "PluginDaemonBadRequestError":
                raise PluginDaemonBadRequestError(message)
            case "PluginDaemonNotFoundError":
                raise PluginDaemonNotFoundError(message)
            case "PluginUniqueIdentifierError":
                raise PluginUniqueIdentifierError(message)
            case "PluginNotFoundError":
                raise PluginNotFoundError(message)
            case "PluginDaemonUnauthorizedError":
                raise PluginDaemonUnauthorizedError(message)
            case "PluginPermissionDeniedError":
                raise PluginPermissionDeniedError(message)
            case _:
                raise Exception(f"got unknown error from plugin daemon: {error_type}, message: {message}")
