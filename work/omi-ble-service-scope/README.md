# Omi Python SDK: service-scoped notification lookup

Status: independent offline reproduction and candidate patch, not an accepted
upstream fix, reserved bounty, or income. Prepared with OpenAI ChatGPT assistance
for GitHub account `zyykk123abc-dotcom`, with the account owner's authorization.
No human hardware review is claimed.

## Problem reproduced

In `sdks/python/omi/ble.py` (Git blob
`6b434b6075682bfff9e94f5ce0c7e9b3c43ced88`), `listen()` accepts
`service_uuid` but never uses it. It passes only `char_uuid` to
`BleakClient.start_notify()`, so resolution occurs over every characteristic on
the device instead of inside the selected service.

The SDK pins Bleak 0.22.3. Its actual GATT collection rejects a UUID that occurs
on multiple characteristics. Consequently:

1. Two services expose the same characteristic UUID: listening with the second
   service's UUID raises `Multiple Characteristics with this UUID` instead of
   selecting the second service's characteristic.
2. The requested service is absent but another service has the characteristic:
   the listener subscribes anyway.
3. The requested service exists without the characteristic but another service
   has it: the listener subscribes outside the requested service.

These are synthetic GATT layouts. They establish the parameter/lookup behavior;
no affected physical Omi device or production incident is asserted.

## Candidate

Resolve `client.services.get_service(service_uuid)`, then resolve the
characteristic within that service and pass the resulting characteristic object
to `start_notify()`. Missing service/characteristic raises `BleakError` before
notification subscription. Defaults, bytes callbacks and payload header handling
are retained. See `candidate.patch`. This is a candidate contract for maintainer
review, not a ready-to-merge upstream PR.

## Run the exact offline checks

Python 3.13.5 / Linux x86_64 was used. No third-party installation is required for
this reproduction bundle. From this directory:

```sh
SOURCE_SET=upstream python tests/test_service_scope.py
SOURCE_SET=candidate python tests/test_service_scope.py
```

The upstream run intentionally exits 1: 4 checks pass and 3 error.
The candidate exits 0: 7 checks pass. Original logs are in `logs/`.
The harness verifies the Git blob hashes of the Omi modules and Bleak service
module before executing them.

## What is real, and what is a fixture

Real upstream code: complete Omi `ble.py` and `constants.py`, complete Bleak
0.22.3 GATT service/collection module, and the `BleakClient.start_notify` method
excerpt from `bleak/__init__.py` (parent Git blob
`68e178125cf28848dc83440f52acc0dc80f96ca4`). The method is only dedented from its
class; it is not a rewritten lookup implementation.

Fixtures: BLE transport, device/characteristic records, exception classes,
UUID helper imports and human-readable UUID descriptions. UUID fixtures use
full UUID strings; abbreviation behavior is not under test. A deterministic
`ProbeComplete` exception ends successful probes after notification delivery,
before the listener's intentional infinite loop. The context manager's exit is
asserted, but real disconnect/cancellation behavior is not claimed tested.

Not performed: a radio connection, physical hardware test, complete installed
Bleak package run, full SDK suite, repository-wide preflight, hosted CI, real
account/API access or payment processing. No live production data was used.

## Sources and license

- Omi source: https://github.com/BasedHardware/omi/blob/main/sdks/python/omi/ble.py
- SDK dependency pin: https://github.com/BasedHardware/omi/blob/main/sdks/python/pyproject.toml
- Bleak 0.22.3 service module: https://github.com/hbldh/bleak/blob/v0.22.3/bleak/backends/service.py
- Bleak 0.22.3 notification dispatch: https://github.com/hbldh/bleak/blob/v0.22.3/bleak/__init__.py
- Bleak's documented duplicate-characteristic behavior: https://bleak.readthedocs.io/en/develop/usage.html
- Omi contribution/bounty proposal policy: https://github.com/BasedHardware/omi/blob/main/docs/doc/developer/Contribution.mdx

Upstream MIT notices are retained in `OMI_LICENSE.txt` and `BLEAK_LICENSE.txt`.
The original fixture/test code in this bundle is offered under MIT on the same
terms; no ownership of upstream code is asserted.

## Commercial status

A US$10 bounty for an accepted correction and repository regression coverage is
proposed, not approved. Scope, delivery channel, eligibility, payout route and
acceptance must be confirmed by the maintainer. Amount earned/received: US$0.
The reproduction is provided for technical review regardless of whether a
bounty is approved. Payment details are intentionally absent.
