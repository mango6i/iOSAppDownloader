# Bundled ipatool 2.8.1 compatibility build

- Project: https://github.com/majd/ipatool
- Base version: v2.8.1, Windows AMD64, MIT license (see LICENSE).
- Release: https://github.com/majd/ipatool/releases/tag/v2.8.1
- Download: https://github.com/majd/ipatool/releases/download/v2.8.1/ipatool-2.8.1-windows-amd64.tar.gz
- Archive SHA-256: `a8ccd8075bc083f99caa49976997860ba5e0e3e8f76b450360cd805262542e97`
- Executable SHA-256: `1c8145d4b39ff993ebce7cf832d5504ed563cc1526bb21ef5cef27d28aceb2dd`
- Compatible build SHA-256: `6acffaf80309ffa920ccf89d4413eba6295e397fe9c38924d1176ea0a252171a`

The official binary above is a reference, not the bundled executable. The
bundled executable is built from the pinned official v2.8.1 source archive
(SHA-256 `88704a28231ac0019016c1900edebc9dea0cf14de4e5bc90aa96fd594925bdc0`)
with the private-root replacement `ipatool/compat/http_client.go`, a bundled
134-region storefront baseline and two exact source anchors: seed the production
client's region map, and emit non-secret storefront/country metadata in auth
login/info JSON. `build_engine.py` records every integration change. Unknown
IDs still use upstream dynamic discovery; neither account permissions nor
credentials are inferred from the GUI, email address or network location.

The private-root replacement embeds the public Apple Root CA, pins SHA-256
`b0b1730ecbc7ff4505142c49f1295e6eda6bcaed7e2c68c5be91b5a11001f024`, and
adds it only to the authentication HTTP client's private certificate pool when
required. There are no certificate-store writes, administrator prompts,
disabled TLS checks, or changes to the authentication protocol. This removes
the first-login dependency on Apple's root-certificate URL returning HTTP 200.

`ipatool/compat/storefronts.json` is the offline baseline from the MIT-licensed
https://github.com/majd/ipatool/blob/v2.7.0/pkg/appstore/storefront.go . The engine
and GUI share this resource. A signed-in account's actual `storeFront` is the
authority, including numeric suffix normalization; an unknown ID is never
silently assigned to US/CN. Known IDs do not depend on `availableStoreFronts`.

`python prepare_engine.py` reproduces this build using `build_engine.py` before source runs/builds
and is not committed to Git. Packaged releases already contain it. This avoids
keeping duplicate large third-party executables in the source repository.
This replaces the old Kosthi/ipatool-rs backend; it is not the abandoned
independent Python authentication implementation.

The official engine handles signed Apple authentication, phone-number Apple
IDs, 2FA, version discovery/metadata, free licenses and IPA downloads. The GUI
uses its non-interactive JSON interface and iPhone platform, not its MCP server
or other-platform commands. No browser or third-party signing service is used.

The build uses pinned Go 1.27.4, source/Go archive hashes, deterministic flags,
Go module checksums, the private-certificate tests and final executable hash.
If the exact toolchain is unavailable, it is downloaded into the temporary
build workspace only, not installed globally. End users need no build tools.

Credentials/cookies live in a unique per-launch state directory with a random
keychain passphrase; they are deleted on normal exit. Runtime assets use a
separate persistent cache. If no verified local seed is available, upstream
downloads its pinned modern Apple frameworks and Unicorn runtime on first use and verifies
their hashes. The GUI does not import Python Unicorn or require its wheel.

Apple decides whether to issue a trusted-device prompt. Clearing local sessions
prevents local remembered login, but cannot force Apple's server to request 2FA.

2.8.1 includes the 2.8.0 local Anisette/provisioning authentication changes,
modern store operations, dynamic storefront discovery, delisted-app recovery
and internal parallel download streams. The GUI preserves Anisette state for
the matching code continuation, not across sign-out or application exits.
