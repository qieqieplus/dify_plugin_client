class PluginError(Exception):
    pass

class PluginDaemonInnerError(PluginError):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")

class PluginInvokeError(PluginError):
    pass

class PluginDaemonInternalServerError(PluginError):
    pass

class PluginDaemonBadRequestError(PluginError):
    pass

class PluginDaemonNotFoundError(PluginError):
    pass

class PluginUniqueIdentifierError(PluginError):
    pass

class PluginNotFoundError(PluginError):
    pass

class PluginDaemonUnauthorizedError(PluginError):
    pass

class PluginPermissionDeniedError(PluginError):
    pass
