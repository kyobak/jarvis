"""Helper process for AppleSpeechEngine: reads {"path": wav} lines, writes {"text"} lines."""

from __future__ import annotations

import json
import sys
import threading

import Foundation
import Speech

LOCALE = "ko-KR"


def authorize() -> None:
    status = Speech.SFSpeechRecognizer.authorizationStatus()
    if status == Speech.SFSpeechRecognizerAuthorizationStatusAuthorized:
        return
    done = threading.Event()
    result: dict[str, int] = {}

    def handler(s: int) -> None:
        result["status"] = s
        done.set()

    Speech.SFSpeechRecognizer.requestAuthorization_(handler)
    done.wait(60)
    if result.get("status") != Speech.SFSpeechRecognizerAuthorizationStatusAuthorized:
        raise PermissionError("speech recognition not authorized")


def make_recognizer():
    locale = Foundation.NSLocale.localeWithLocaleIdentifier_(LOCALE)
    recognizer = Speech.SFSpeechRecognizer.alloc().initWithLocale_(locale)
    if recognizer is None or not recognizer.isAvailable():
        raise RuntimeError(f"no recognizer for {LOCALE}")
    # Deliver callbacks on a background queue; this process has no main run loop.
    recognizer.setQueue_(Foundation.NSOperationQueue.alloc().init())
    return recognizer


def transcribe(recognizer, path: str) -> str:
    url = Foundation.NSURL.fileURLWithPath_(path)
    request = Speech.SFSpeechURLRecognitionRequest.alloc().initWithURL_(url)
    request.setShouldReportPartialResults_(False)
    if recognizer.supportsOnDeviceRecognition():
        request.setRequiresOnDeviceRecognition_(True)
    done = threading.Event()
    out: dict[str, str] = {}

    def handler(result, error) -> None:
        if error is not None:
            out["error"] = str(error.localizedDescription())
            done.set()
        elif result is not None and result.isFinal():
            out["text"] = str(result.bestTranscription().formattedString())
            done.set()

    task = recognizer.recognitionTaskWithRequest_resultHandler_(request, handler)
    if not done.wait(20):
        task.cancel()
        raise TimeoutError("recognition timed out")
    if "error" in out:
        raise RuntimeError(out["error"])
    return out.get("text", "")


def main() -> None:
    try:
        authorize()
        recognizer = make_recognizer()
    except Exception as e:
        print(json.dumps({"error": str(e)}), flush=True)
        return
    for line in sys.stdin:
        try:
            text = transcribe(recognizer, json.loads(line)["path"])
            print(json.dumps({"text": text}, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"error": str(e)}), flush=True)


if __name__ == "__main__":
    main()
