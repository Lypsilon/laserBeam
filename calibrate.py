# calibrate.py
# Full-screen gaze calibration with perspective transform,
# single-point redo, and manual arrow-key adjustment.

import pygame
import json
import numpy as np
import cv2
import time
import argparse
from pupil_labs.realtime_api.simple import discover_one_device

CAMERA_FILE = "scene_camera.json"
CALIB_FILE = "calibration.json"
SAMPLES_PER_POINT = 30
SAMPLE_INTERVAL = 0.01


def run_calibration(display_index=1):
    # --------------------------
    # CAMERA PARAMS
    # --------------------------
    def load_camera_params():
        with open(CAMERA_FILE, "r") as f:
            data = json.load(f)
        cam_matrix = np.array(data["camera_matrix"], dtype=np.float32)
        dist_coeffs = np.array(data["distortion_coefficients"], dtype=np.float32)
        resolution = (1600, 1200)  # hard-coded scene camera resolution
        return cam_matrix, dist_coeffs, resolution

    CAM_MATRIX, DIST_COEFFS, RESOLUTION = load_camera_params()

    def undistort_point(x, y):
        pts = np.array([[[x, y]]], dtype=np.float32)
        undistorted = cv2.undistortPoints(pts, CAM_MATRIX, DIST_COEFFS)
        u, v = undistorted[0][0]
        fx, fy = CAM_MATRIX[0, 0], CAM_MATRIX[1, 1]
        cx, cy = CAM_MATRIX[0, 2], CAM_MATRIX[1, 2]
        px = u * fx + cx
        py = v * fy + cy
        return px, py

    # --------------------------
    # PYGAME SETUP
    # --------------------------
    pygame.init()
    num_displays = pygame.display.get_num_displays()
    DISPLAY_INDEX = display_index if display_index < num_displays else 0

    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN, display=DISPLAY_INDEX)
    WIDTH, HEIGHT = screen.get_size()
    font = pygame.font.SysFont(None, 48)
    clock = pygame.time.Clock()

    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    RED = (255, 0, 0)
    GREEN = (0, 255, 0)
    CYAN = (0, 255, 255)

    # --------------------------
    # CALIBRATION POINTS
    # --------------------------
    calibration_points = [
        (WIDTH // 2, HEIGHT // 2),       # center
        (100, 100),                      # top-left
        (WIDTH - 100, 100),              # top-right
        (100, HEIGHT - 100),             # bottom-left
        (WIDTH - 100, HEIGHT - 100)      # bottom-right
    ]
    NUM_POINTS = len(calibration_points)
    captured_points = [None] * NUM_POINTS

    # init screen
    screen.fill(BLACK)
    msg = font.render("Initializing... Please wait", True, WHITE)
    screen.blit(msg, (WIDTH // 2 - 200, HEIGHT // 2))
    pygame.display.flip()

    # --------------------------
    # CONNECT TO PUPIL LABS
    # --------------------------
    print("Looking for Pupil Labs device...")
    device = discover_one_device(max_search_duration_seconds=10)
    if device is None:
        print("No device found.")
        raise SystemExit(-1)
    print("Device connected!")

    # --------------------------
    # PREP
    # --------------------------
    print("Warming up gaze stream...")
    phase = "init"
    warmup_start = time.time()
    warmup_duration = 2.0
    warmup_samples = 30
    samples_collected = 0

    # pre-create file
    with open(CALIB_FILE, "w") as f:
        json.dump([], f)

    # --------------------------
    # HELPER
    # --------------------------
    def recompute_homography():
        nonlocal homography
        pts = [p for p in captured_points if p is not None]
        if len(pts) >= 4:
            src = np.array([p["gaze"] for p in pts], dtype=np.float32)
            dst = np.array(
                [p["adjusted"] if p["adjusted"] is not None else p["screen"] for p in pts],
                dtype=np.float32,
            )
            homography, _ = cv2.findHomography(src, dst, method=0)
        else:
            homography = None

    # --------------------------
    # MAIN LOOP
    # --------------------------
    current_index = 0
    redo_index = None
    manual_edit_index = None
    homography = None
    running = True

    while running:
        screen.fill(BLACK)

        if phase == "init":
            msg = font.render("Initializing... Please wait", True, WHITE)
            screen.blit(msg, (WIDTH // 2 - 200, HEIGHT // 2))

            gaze = device.receive_gaze_datum()
            if gaze:
                samples_collected += 1

            if (time.time() - warmup_start > warmup_duration) or (
                samples_collected >= warmup_samples
            ):
                print("Warm-up finished. Starting calibration.")
                phase = "capture"
                current_index = 0

        elif phase == "capture":
            idx = redo_index if redo_index is not None else current_index
            cx, cy = calibration_points[idx]
            pygame.draw.circle(screen, RED, (cx, cy), 20)
            msg = font.render("Please look at the dot.", True, WHITE)
            screen.blit(msg, (50, 50))

        elif phase == "replay":
            for i, screen_pt in enumerate(calibration_points):
                sx, sy = screen_pt
                pygame.draw.circle(screen, RED, (sx, sy), 20)

                if captured_points[i] is not None and homography is not None:
                    gaze_pt = np.array([[[*captured_points[i]["gaze"]]]], dtype=np.float32)
                    mapped_pt = cv2.perspectiveTransform(gaze_pt, homography)[0][0]
                    gx, gy = mapped_pt
                    pygame.draw.circle(screen, GREEN, (int(gx), int(gy)), 15)

            print("Replay mode: 1-5=redo, SHIFT+1-5=manual edit, ESC=finish")

        elif phase == "manual_edit":
            idx = manual_edit_index
            sx, sy = calibration_points[idx]
            gx, gy = captured_points[idx]["adjusted"]

            pygame.draw.circle(screen, RED, (sx, sy), 20)
            pygame.draw.circle(screen, GREEN, (sx, sy), 15, 2)
            pygame.draw.circle(screen, CYAN, (int(gx), int(gy)), 10)

        elif phase == "done":
            msg = font.render("Calibration complete!", True, WHITE)
            screen.blit(msg, (50, 50))
            print("Calibration complete! Press ESC to exit.")

        pygame.display.flip()

        # --------------------------
        # EVENT HANDLING
        # --------------------------
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if phase == "manual_edit":
                        manual_edit_index = None
                        phase = "replay"
                    else:
                        running = False

                elif phase == "capture" and event.key == pygame.K_SPACE:
                    idx = redo_index if redo_index is not None else current_index
                    samples = []
                    for _ in range(SAMPLES_PER_POINT):
                        gaze = device.receive_gaze_datum()
                        if gaze and gaze.worn:
                            gx, gy = undistort_point(gaze.x, gaze.y)
                            samples.append([gx, gy])
                        time.sleep(SAMPLE_INTERVAL)

                    print(f"Collected {len(samples)} samples at point {idx+1}")

                    if len(samples) >= int(SAMPLES_PER_POINT * 0.7):
                        avg = np.mean(np.array(samples), axis=0)
                        cx, cy = calibration_points[idx]
                        gaze = [float(avg[0]), float(avg[1])]

                        captured_points[idx] = {
                            "gaze": gaze,
                            "screen": [cx, cy],
                            "adjusted": None,  # default = None
                        }

                        print(
                            f"Captured point {idx+1}: gaze={avg} -> screen=({cx},{cy})"
                        )

                        if redo_index is None:
                            current_index += 1
                            if current_index >= NUM_POINTS:
                                recompute_homography()
                                phase = "replay"
                        else:
                            redo_index = None
                            recompute_homography()
                            phase = "replay"
                    else:
                        print("Not enough valid samples, try again.")

                elif phase == "replay":
                    if pygame.K_1 <= event.key <= pygame.K_5:
                        idx = event.key - pygame.K_1
                        if idx < NUM_POINTS and captured_points[idx] is not None:
                            if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                                manual_edit_index = idx
                                if homography is not None:
                                    gaze_pt = np.array(
                                        [[[ *captured_points[idx]["gaze"] ]]],
                                        dtype=np.float32,
                                    )
                                    mapped_pt = cv2.perspectiveTransform(
                                        gaze_pt, homography
                                    )[0][0]
                                    captured_points[idx]["adjusted"] = [
                                        float(mapped_pt[0]),
                                        float(mapped_pt[1]),
                                    ]
                                else:
                                    captured_points[idx]["adjusted"] = captured_points[idx]["screen"][:]
                                print(
                                    f"Manual edit mode for point {manual_edit_index+1}"
                                )
                                phase = "manual_edit"
                            else:
                                redo_index = idx
                                captured_points[idx] = None
                                print(f"Redoing point {redo_index+1}")
                                phase = "capture"

                elif phase == "manual_edit" and manual_edit_index is not None:
                    gx, gy = captured_points[manual_edit_index]["adjusted"]
                    step = 5
                    if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                        step = 20
                    if event.key == pygame.K_UP:
                        gy -= step
                    elif event.key == pygame.K_DOWN:
                        gy += step
                    elif event.key == pygame.K_LEFT:
                        gx -= step
                    elif event.key == pygame.K_RIGHT:
                        gx += step
                    elif event.key == pygame.K_RETURN:
                        print(
                            f"Manual edit confirmed for point {manual_edit_index+1}"
                        )
                        captured_points[manual_edit_index]["adjusted"] = [gx, gy]
                        recompute_homography()
                        manual_edit_index = None
                        phase = "replay"
                        continue

                    captured_points[manual_edit_index]["adjusted"] = [gx, gy]

        clock.tick(60)

    # --------------------------
    # SAVE CALIBRATION
    # --------------------------
    with open(CALIB_FILE, "w") as f:
        json.dump([p for p in captured_points if p is not None], f, indent=2)
        print(f"Calibration saved to {CALIB_FILE}")

    pygame.quit()
    device.close()
    return homography


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--display",
        type=int,
        default=1,
        help="Monitor index (default=1, fallback to 0 if not available)",
    )
    args = parser.parse_args()
    run_calibration(display_index=args.display)
