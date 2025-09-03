# calibrate.py
# Full-screen gaze calibration with perspective transform and single-point redo

import pygame
import json
import numpy as np
import cv2
import time
from pupil_labs.realtime_api.simple import discover_one_device

# --------------------------
# CONFIG
# --------------------------
CAMERA_FILE = "scene_camera.json"
CALIB_FILE = "calibration.json"
WINDOW_RES = (1920, 1080)  # full-screen size
SAMPLES_PER_POINT = 30
SAMPLE_INTERVAL = 0.01

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
# CALIBRATION POINTS
# --------------------------
calibration_points = [
    (WINDOW_RES[0] // 2, WINDOW_RES[1] // 2),  # center
    (100, 100),                                # top-left
    (WINDOW_RES[0] - 100, 100),                # top-right
    (100, WINDOW_RES[1] - 100),                # bottom-left
    (WINDOW_RES[0] - 100, WINDOW_RES[1] - 100) # bottom-right
]
NUM_POINTS = len(calibration_points)

# Initialize slots for captured points (None if not captured yet)
captured_points = [None] * NUM_POINTS

# --------------------------
# PYGAME SETUP
# --------------------------
pygame.init()
screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
WIDTH, HEIGHT = screen.get_size()
font = pygame.font.SysFont(None, 48)
clock = pygame.time.Clock()

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED   = (255, 0, 0)
GREEN = (0, 255, 0)

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
# MAIN LOOP
# --------------------------
phase = "capture"  # capture -> replay -> done
current_index = 0
redo_index = None  # index of point to redo
homography = None
running = True

while running:
    screen.fill(BLACK)

    if phase == "capture":
        idx = redo_index if redo_index is not None else current_index
        cx, cy = calibration_points[idx]
        pygame.draw.circle(screen, RED, (cx, cy), 20)
        msg = font.render(f"Look at the dot and press SPACE ({idx+1}/{NUM_POINTS})", True, WHITE)
        screen.blit(msg, (50, 50))

    elif phase == "replay":
        # Draw all points at once
        valid_points = [p for p in captured_points if p is not None]
        if homography is not None and len(valid_points) > 0:
            gaze_coords = np.array([p["gaze"] for p in valid_points], dtype=np.float32).reshape(-1,1,2)
            mapped = cv2.perspectiveTransform(gaze_coords, homography).reshape(-1,2)
            mapped_idx = 0
        for i, screen_pt in enumerate(calibration_points):
            sx, sy = screen_pt
            pygame.draw.circle(screen, RED, (sx, sy), 20)
            if captured_points[i] is not None:
                if homography is not None:
                    gx, gy = mapped[mapped_idx]
                    mapped_idx += 1
                else:
                    gx, gy = captured_points[i]["screen"]
                pygame.draw.circle(screen, GREEN, (int(gx), int(gy)), 15)
            num_text = font.render(str(i+1), True, WHITE)
            screen.blit(num_text, (sx-10, sy-10))
        msg = font.render("Press 1-5 to redo any point, ESC to finish.", True, WHITE)
        screen.blit(msg, (50, 50))

    elif phase == "done":
        msg = font.render("Calibration complete! Press ESC to exit.", True, WHITE)
        screen.blit(msg, (50, 50))

    pygame.display.flip()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
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
                if len(samples) > 0:
                    avg = np.mean(np.array(samples), axis=0)
                    cx, cy = calibration_points[idx]
                    captured_points[idx] = {"gaze": [float(avg[0]), float(avg[1])], "screen": [cx, cy]}
                    print(f"Captured point {idx+1}: gaze={avg} -> screen=({cx},{cy})")
                    if redo_index is None:
                        current_index += 1
                        if current_index >= NUM_POINTS:
                            # Compute homography using all captured points
                            src = np.array([p["gaze"] for p in captured_points if p is not None], dtype=np.float32)
                            dst = np.array([p["screen"] for p in captured_points if p is not None], dtype=np.float32)
                            homography, _ = cv2.findHomography(src, dst, method=0)
                            phase = "replay"
                    else:
                        # finished redo, return to replay
                        redo_index = None
                        # recompute homography with updated point
                        src = np.array([p["gaze"] for p in captured_points if p is not None], dtype=np.float32)
                        dst = np.array([p["screen"] for p in captured_points if p is not None], dtype=np.float32)
                        homography, _ = cv2.findHomography(src, dst, method=0)
                        phase = "replay"

            elif phase == "replay":
                if pygame.K_1 <= event.key <= pygame.K_5:
                    redo_index = event.key - pygame.K_1
                    if redo_index < NUM_POINTS:
                        print(f"Redoing point {redo_index+1}")
                        captured_points[redo_index] = None
                        phase = "capture"

    clock.tick(60)

# --------------------------
# SAVE CALIBRATION
# --------------------------
with open(CALIB_FILE, "w") as f:
    json.dump([p for p in captured_points if p is not None], f, indent=2)
    print(f"Calibration saved to {CALIB_FILE}")

pygame.quit()
device.close()