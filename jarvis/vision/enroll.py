"""`jarvis enroll`: learn the owner's face and resting eye/head baselines.

Stores an averaged SFace vector and two numbers in face_profile.npz. No photos are saved.
"""

from __future__ import annotations

import statistics
import time

from jarvis.core.config import Config, default_data_dir

SAMPLES = 20
BASELINE_SECONDS = 5


def profile_path():
    return default_data_dir() / "face_profile.npz"


def run_enroll(config: Config) -> int:
    try:
        import cv2
        import numpy as np

        from jarvis.vision.face import FaceEngine, FaceProfile, ear_of, make_eye_landmarks
    except ImportError:
        print("얼굴 등록에는 비전 패키지가 필요해요: uv sync --extra vision --extra vision-mediapipe")
        return 1

    print("모델을 준비하는 중이에요 (처음 한 번은 다운로드 때문에 오래 걸려요)…")
    engine = FaceEngine()
    eyes = make_eye_landmarks()
    cap = cv2.VideoCapture(config.vision.camera_index)
    if not cap.isOpened():
        print("카메라를 열 수 없어요. 시스템 설정 → 개인정보 보호 → 카메라에서 터미널을 허용해 주세요.")
        return 1

    embeddings: list = []
    ears: list[float] = []
    pitches: list[float] = []
    print(f"\n1단계: 카메라를 편하게 정면으로 보고 눈을 평소처럼 뜬 채로 {BASELINE_SECONDS}초만 있어 주세요.")
    input("준비되면 Enter…")
    try:
        end = time.monotonic() + BASELINE_SECONDS
        while time.monotonic() < end:
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.resize(frame, (320, 240))
            faces = engine.detect(frame)
            if len(faces) != 1:
                continue
            face = faces[0]
            if face.frontal:
                pitches.append(face.pitch)
                if eyes:
                    e = eyes.eyes(frame, face)
                    if e:
                        ears.append(ear_of(e))
                embeddings.append(engine.embedding(frame, face))
        print(f"\n2단계: 천천히 고개를 좌우·위아래로 조금씩 움직여 주세요. 사진 {SAMPLES}장을 모을게요 (사진은 저장하지 않아요).")
        last = 0.0
        deadline = time.monotonic() + 60
        while len(embeddings) < SAMPLES + 5 and time.monotonic() < deadline:
            ok, frame = cap.read()
            if not ok or time.monotonic() - last < 0.4:
                continue
            frame = cv2.resize(frame, (320, 240))
            faces = engine.detect(frame)
            if len(faces) != 1 or faces[0].score < 0.85:
                continue
            embeddings.append(engine.embedding(frame, faces[0]))
            last = time.monotonic()
            print(f"  {len(embeddings)}/{SAMPLES + 5}", end="\r", flush=True)
    finally:
        cap.release()

    if len(embeddings) < 8 or not pitches:
        print("\n얼굴을 충분히 찾지 못했어요. 밝은 곳에서 혼자 카메라 앞에 앉아 다시 시도해 주세요.")
        return 1
    mean = np.mean(np.stack(embeddings), axis=0)
    mean /= np.linalg.norm(mean)
    baseline_ear = statistics.median(ears) if ears else 0.28
    baseline_pitch = statistics.median(pitches)
    FaceProfile(mean.astype(np.float32), baseline_ear, baseline_pitch).save(profile_path())
    print(f"\n등록 완료! (눈 기준값 {baseline_ear:.3f}, 고개 기준값 {baseline_pitch:.2f})")
    print(f"저장 위치: {profile_path()} — 지우면 등록이 취소돼요. 자비스를 다시 시작하면 적용돼요.")
    return 0
