# Bundled official ipatool

- Project: https://github.com/majd/ipatool
- Version: v2.7.0, Windows AMD64, MIT license (see LICENSE).
- Release: https://github.com/majd/ipatool/releases/tag/v2.7.0
- Download: https://github.com/majd/ipatool/releases/download/v2.7.0/ipatool-2.7.0-windows-amd64.tar.gz
- Archive SHA-256: `b729608716908be287c2e6972f9e8cd05f879810ae5d182fc856c9e57cca0dd5`
- Executable SHA-256: `7b83589b74ad533f5d5dbab0ca87a5cb76b123bcbeb2553d57e9c154e35d8755`

`ipatool.exe` is the unmodified `bin/ipatool-2.7.0-windows-amd64.exe` from
the official archive. Verify the archive hash before replacing this file.
The binary is prepared by `python prepare_engine.py` before source runs/builds
and is not committed to Git. Packaged releases already contain it. This avoids
keeping duplicate large third-party executables in the source repository.
This replaces the old Kosthi/ipatool-rs backend; it is not the abandoned
independent Python authentication implementation.

The official engine handles signed Apple authentication, phone-number Apple
IDs, 2FA, version discovery/metadata, free licenses and IPA downloads. The GUI
uses its non-interactive JSON interface and iPhone platform, not its MCP server
or other-platform commands. No browser or third-party signing service is used.

Credentials/cookies live in a unique per-launch state directory with a random
keychain passphrase; they are deleted on normal exit. Runtime assets use a
separate persistent cache. If no verified local seed is available, upstream
downloads its pinned Apple assets and Unicorn runtime on first use and verifies
their hashes. The GUI does not import Python Unicorn or require its wheel.

Apple decides whether to issue a trusted-device prompt. Clearing local sessions
prevents local remembered login, but cannot force Apple's server to request 2FA.
