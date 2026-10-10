"""SAP setup transport and signer interfaces.

The HTTP part is independent code.  The local machine is intentionally an
interface: it is the small boundary where the Apple CoreFP/CommerceKit
runtime will be connected, without making the application launch ipatool.
"""

import base64
import plistlib
from typing import Protocol

from .errors import ProtocolError, SapRequiredError
from .models import SapConfig


class ActionSigner(Protocol):
    def sign(self, body):
        """Return the raw SAP signature for exact request bytes."""


class SapMachine(Protocol):
    def initialize(self, hardware_id):
        """Return an opaque local SAP context."""

    def exchange(self, version, hardware_id, context, incoming):
        """Return (outgoing_buffer, state), where state 1 awaits Apple."""

    def sign(self, context, body):
        """Sign exact body bytes."""

    def teardown(self, context):
        """Release local SAP context."""


def _plist_bytes(document, key):
    try:
        values = plistlib.loads(document)
    except Exception as exc:
        raise ProtocolError("SAP response is not a valid plist") from exc
    if not isinstance(values, dict) or not isinstance(values.get(key), bytes):
        raise ProtocolError("SAP response is missing %s" % key)
    value = values[key]
    if not value:
        raise ProtocolError("SAP response contains an empty %s" % key)
    return value


class SapSession:
    """Owns one Apple handshake and exposes an action signer."""

    def __init__(self, transport, config, machine, hardware_id):
        if not isinstance(config, SapConfig):
            raise TypeError("config must be SapConfig")
        self.transport = transport
        self.config = config
        self.machine = machine
        self.hardware_id = bytes(hardware_id)
        self.context = None
        self.established = False

    def establish(self):
        if not self.hardware_id or len(self.hardware_id) > 20:
            raise ProtocolError("hardware ID must contain 1-20 bytes")
        self.context = self.machine.initialize(self.hardware_id)
        try:
            cert_response = self.transport.request("GET", self.config.certificate_url)
            if cert_response.status != 200:
                raise SapRequiredError("SAP certificate request returned HTTP %d" % cert_response.status)
            certificate = _plist_bytes(cert_response.body, "sign-sap-setup-cert")
            outgoing, state = self.machine.exchange(
                self.config.version, self.hardware_id, self.context, certificate
            )
            if state != 1 or not outgoing:
                raise ProtocolError("local SAP machine did not produce setup data")
            envelope = plistlib.dumps(
                {"sign-sap-setup-buffer": outgoing}, fmt=plistlib.FMT_XML, sort_keys=False
            )
            response = self.transport.request(
                "POST",
                self.config.setup_url,
                body=envelope,
                headers={"Content-Type": "application/x-plist"},
            )
            if response.status != 200:
                raise SapRequiredError("SAP setup request returned HTTP %d" % response.status)
            reply = _plist_bytes(response.body, "sign-sap-setup-buffer")
            _, final_state = self.machine.exchange(
                self.config.version, self.hardware_id, self.context, reply
            )
            if final_state != 0:
                raise ProtocolError("local SAP machine did not finish setup")
            self.established = True
            return self
        except Exception:
            self.close()
            raise

    def sign(self, body):
        if not self.established or self.context is None:
            raise SapRequiredError("SAP session is not established")
        signature = self.machine.sign(self.context, bytes(body))
        if not signature:
            raise ProtocolError("SAP machine returned an empty signature")
        return base64.b64encode(signature).decode("ascii")

    def close(self):
        if self.context is not None:
            try:
                self.machine.teardown(self.context)
            finally:
                self.context = None
                self.established = False
