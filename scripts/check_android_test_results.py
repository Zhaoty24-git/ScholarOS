"""Require actual, complete emulator instrumentation results before uploading APK."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def check(directory):
    files = list(Path(directory).rglob("TEST-*.xml"))
    if not files: raise ValueError("Missing emulator test reports")
    totals = dict(tests=0, failures=0, errors=0, skipped=0)
    names = set()
    for file in files:
        root = ET.parse(file).getroot()
        for key in totals: totals[key] += int(root.attrib.get(key, 0))
        for case in root.findall("testcase"): names.add(case.attrib.get("name"))
    expected = {"launchWithoutNetworkOrCredentials", "courseDetailAndNativeBack", "assignmentDetailsAndLongList", "noticesMaterialsSettingsAndRotation"}
    # PR4 must preserve the four offline cases and also run native vault/protocol
    # and real bridge/UI Mock cases; zero/skipped AI acceptance cannot be green.
    ai_expected = {"keystoreEncryptedPersistenceAndReload", "keystoreDeleteAndMemoryOnlyMode", "replacementInvalidatesPreviousKeyMaterial", "malformedKeyAndProviderRejected", "modelRolesAndBothRegionPaths", "rejectsInjectedRolesAndMalformedResponse", "realLocalMockServiceRoundtrip", "unauthorizedRateLimitServerAndRedirectAreSanitized", "timeoutsAndTlsErrorsNeverFallback", "streamingChunksAndIncompleteStreamValidation", "cancellationAndDownloadLimit", "aiMultiTurnContextMarkdownAndKeyDeletion", "aiStreamingCancelAndSafeErrors"}
    expected |= ai_expected
    expected.add("tamperedRegionCannotDecryptKey")
    if not expected <= names or totals["tests"] < len(expected) or any(totals[k] for k in ("failures", "errors", "skipped")):
        raise ValueError("Incomplete or failing emulator acceptance: " + str(totals))
    return totals


if __name__ == "__main__":
    result = check(sys.argv[1])
    print("::notice title=Android emulator acceptance::" + str(result))
