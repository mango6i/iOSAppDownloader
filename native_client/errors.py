"""Errors exposed by the independent Apple client."""


class NativeClientError(Exception):
    """Base class for expected client-side failures."""


class ProtocolError(NativeClientError):
    """Apple returned data that does not match the expected protocol."""


class TransportError(NativeClientError):
    """The request could not be completed."""


class SapRequiredError(NativeClientError):
    """The endpoint requires an SAP action signature."""


class AuthenticationError(NativeClientError):
    """Authentication could not be completed."""


class AuthenticationRejected(AuthenticationError):
    """Apple rejected the credentials or the verification code."""


class TwoFactorRequired(AuthenticationError):
    """Apple requires a code from a trusted device."""

    def __init__(self, message="Apple requires a six-digit verification code"):
        super().__init__(message)


class LoginIncomplete(AuthenticationError):
    """A login operation is still waiting for a user-provided code."""
