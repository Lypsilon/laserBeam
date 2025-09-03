# eye_laser_game.py
# Run from command line:
#   python eye_laser_game.py           # runs calibration first (default)
#   python eye_laser_game.py --reuse-calibration
#   python eye_laser_game.py --no-eyetracking
#   python eye_laser_game.py --windowed
#   python eye_laser_game.py --timer 60

import pygame
import random
import time
import math
import sys
import os
import csv
import json
import subprocess
import numpy as np

# Pupil Labs realtime API
try:
    from pupil_labs.realtime_api.simple import discover_one_device
except ImportError:
    discover_one_device = None

# OpenCV
import cv2

# Settings (tweak to taste)
ASTEROID_SIZE = 64
FIXATION_HALO_MAX_RADIUS = 80
FIXATION_TIME = 1.0
LASER_FIXATION_THRESHOLD = 0.02
MIN_DISTANCE = ASTEROID_SIZE * 2
MAX_ON_SCREEN = 8
SPAWN_PROBABILITY = 0.02
ASTEROID_RANDOM_DISAPPEAR_CHANCE = 0.0005

SCENE_CAMERA_FILE = "scene_camera.json"
CALIB_FILE = "calibration.json"
CALIB_SCRIPT = "calibrate.py"

# Hard-coded images in visuals folder
BACKGROUND_IMAGE_FILE = os.path.join("visuals", "background.png")
ASTEROID_IMAGE_FILE = os.path.join("visuals", "asteroid.png")

# Command-line args
NO_EYETRACKING = "--no-eyetracking" in sys.argv
WINDOWED = "--windowed" in sys.argv
REUSE_CALIB = "--reuse-calibration" in sys.argv
GAME_DURATION = None
if "--timer" in sys.argv:
    try:
        GAME_DURATION = int(sys.argv[sys.argv.index("--timer")+1])
    except Exception:
        GAME_DURATION = None

# Pygame init
pygame.init()
if WINDOWED:
    screen = pygame.display.set_mode((1280, 720))
else:
    screen = pygame.display.set_mode((0,0), pygame.FULLSCREEN)
WIDTH, HEIGHT = screen.get_size()
pygame.display.set_caption("Eye Laser Game")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 36)
LASER_ORIGIN = (WIDTH // 2, HEIGHT)

# Load visuals
background_img = pygame.image.load(BACKGROUND_IMAGE_FILE).convert()
background_img = pygame.transform.scale(background_img, (WIDTH, HEIGHT))
asteroid_img = pygame.image.load(ASTEROID_IMAGE_FILE).convert_alpha()
asteroid_img = pygame.transform.scale(asteroid_img, (ASTEROID_SIZE, ASTEROID_SIZE))

# Logging
os.makedirs("logs", exist_ok=True)
log_filename = time.strftime("logs/game_%Y%m%d_%H%M%S.csv")
log_file = open(log_filename, "w", newline="", encoding="utf-8")
log_writer = csv.writer(log_file)
log_writer.writerow(["timestamp", "event", "details"])

def log_event(event, details=""):
    log_writer.writerow([time.time(), event, details])
    log_file.flush()

# Utility: load scene camera intrinsics
def load_scene_camera(path):
    if not os.path.exists(path):
        return None, None, None
    with open(path, "r") as f:
        data = json.load(f)
    K = None; D = None; resolution = None
    if "camera_matrix" in data:
        K = np.array(data["camera_matrix"], dtype=float)
    elif "intrinsics" in data and "camera_matrix" in data["intrinsics"]:
        K = np.array(data["intrinsics"]["camera_matrix"], dtype=float)
    if "distortion_coefficients" in data:
        D = np.array(data["distortion_coefficients"], dtype=float)
        if D.ndim > 1:
            D = D.flatten()
    elif "intrinsics" in data and "distortion_coefficients" in data["intrinsics"]:
        D = np.array(data["intrinsics"]["distortion_coefficients"], dtype=float).flatten()
    if "resolution" in data:
        resolution = tuple(data["resolution"])
    elif "image_size" in data:
        resolution = tuple(data["image_size"])
    elif "intrinsics" in data and "resolution" in data["intrinsics"]:
        resolution = tuple(data["intrinsics"]["resolution"])
    return K, D, resolution

def undistort_point_opencv(x, y, K, D):
    if K is None or D is None:
        return float(x), float(y)
    pt = np.array([[[float(x), float(y)]]], dtype=np.float32)  # shape (1,1,2)
    und = cv2.undistortPoints(pt, K, D, P=K)
    ux, uy = und.reshape(-1,2)[0]
    return float(ux), float(uy)

def map_affine(gx, gy, calib):
    px = calib["params_x"]
    py = calib["params_y"]
    X = px[0]*gx + px[1]*gy + px[2]
    Y = py[0]*gx + py[1]*gy + py[2]
    return int(round(X)), int(round(Y))

# Prepare Pupil device and calibration
pl_device = None
K = None; D = None; scene_resolution = None
calibration = None

if not NO_EYETRACKING and discover_one_device:
    print("Looking for Pupil Labs device...")
    pl_device = discover_one_device(max_search_duration_seconds=10)
    if pl_device:
        print("Pupil Labs device connected.")
        # load scene intrinsics if available
        K, D, scene_resolution = load_scene_camera(SCENE_CAMERA_FILE)
        if not REUSE_CALIB or not os.path.exists(CALIB_FILE):
            print("Running calibration (calibrate.py)...")
            subprocess.run([sys.executable, CALIB_SCRIPT])
        else:
            print("Reusing existing calibration.")
        if os.path.exists(CALIB_FILE):
            with open(CALIB_FILE, "r") as f:
                calibration = json.load(f)
            print("Loaded calibration.")
        else:
            print("Calibration file missing; continuing without gaze mapping.")
    else:
        print("No device found, falling back to mouse.")
else:
    print("No eyetracking (mouse control).")

# --- Asteroid class (image + halo) ---
class Asteroid:
    def __init__(self, existing_asteroids):
        valid = False
        while not valid:
            self.x = random.randint(ASTEROID_SIZE, WIDTH - ASTEROID_SIZE)
            self.y = random.randint(ASTEROID_SIZE, HEIGHT - ASTEROID_SIZE)
            self.rect = pygame.Rect(self.x - ASTEROID_SIZE//2, self.y - ASTEROID_SIZE//2, ASTEROID_SIZE, ASTEROID_SIZE)
            valid = True
            for other in existing_asteroids:
                dx = self.x - other.x
                dy = self.y - other.y
                if math.hypot(dx, dy) < MIN_DISTANCE:
                    valid = False
                    break
        self.fixating = False
        self.start_fix = None
        self.type = random.choice(["good","bad"])

    def draw(self, screen):
        # draw asteroid image centered
        screen.blit(asteroid_img, (self.x - ASTEROID_SIZE//2, self.y - ASTEROID_SIZE//2))
        # fixation halo (transparent filled)
        if self.fixating and self.start_fix is not None:
            elapsed = time.time() - self.start_fix
            growth = min(FIXATION_HALO_MAX_RADIUS, int((elapsed / FIXATION_TIME) * FIXATION_HALO_MAX_RADIUS))
            color = (0,255,0) if self.type=="good" else (255,0,0)
            halo_surface = pygame.Surface((growth*2, growth*2), pygame.SRCALPHA)
            pygame.draw.circle(halo_surface, (*color, 100), (growth, growth), growth)
            screen.blit(halo_surface, (self.x - growth, self.y - growth))

    def update(self, cursor_pos):
        if self.rect.collidepoint(cursor_pos):
            if not self.fixating:
                self.fixating = True
                self.start_fix = time.time()
                return "fixation_start"
            else:
                if time.time() - self.start_fix >= FIXATION_TIME:
                    return "destroyed"
        else:
            self.fixating = False
            self.start_fix = None
        return None

# --- Game state ---
asteroids = [Asteroid([])]
score = 0
running = True
explosions = []
EXPLOSION_DURATION = 0.25
laser_fixating = False
laser_start_fix = None
start_time = time.time()

# Main loop
while running:
    dt = clock.tick(60) / 1000.0
    screen.blit(background_img, (0,0))

    # events
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            running = False
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            running = False

    # Get gaze sample
    cursor_pos = pygame.mouse.get_pos()
    if pl_device and calibration:
        try:
            gaze_sample = pl_device.receive_gaze_datum()
            if gaze_sample is not None:
                gx = None; gy = None
                if hasattr(gaze_sample, "x") and hasattr(gaze_sample, "y"):
                    gx_raw = float(gaze_sample.x); gy_raw = float(gaze_sample.y)
                    # undistort raw camera pixel coordinates
                    und_x, und_y = undistort_point_opencv(gx_raw, gy_raw, K, D)
                    # map using affine
                    mx, my = map_affine(und_x, und_y, calibration)
                    # clamp
                    mx = max(0, min(WIDTH-1, mx)); my = max(0, min(HEIGHT-1, my))
                    cursor_pos = (mx, my)
                elif hasattr(gaze_sample, "norm_pos") and gaze_sample.norm_pos is not None:
                    nx, ny = gaze_sample.norm_pos
                    # If scene_resolution known, convert normalized coords to scene pixels first
                    if scene_resolution is not None:
                        gx_raw = nx * scene_resolution[0]
                        gy_raw = ny * scene_resolution[1]
                    else:
                        # fallback - use WIDTH/HEIGHT as approx
                        gx_raw = nx * WIDTH
                        gy_raw = ny * HEIGHT
                    und_x, und_y = undistort_point_opencv(gx_raw, gy_raw, K, D)
                    mx, my = map_affine(und_x, und_y, calibration)
                    mx = max(0, min(WIDTH-1, mx)); my = max(0, min(HEIGHT-1, my))
                    cursor_pos = (mx, my)
                else:
                    # not a gaze datum we can use -> fallback to mouse
                    cursor_pos = pygame.mouse.get_pos()
        except Exception as e:
            # On any exception fallback to mouse
            print("Gaze read error:", e)
            cursor_pos = pygame.mouse.get_pos()

    # spawn
    if len(asteroids) < MAX_ON_SCREEN and random.random() < SPAWN_PROBABILITY:
        asteroids.append(Asteroid(asteroids))

    # update asteroids
    for a in asteroids[:]:
        res = a.update(cursor_pos)
        if res == "fixation_start":
            log_event("fixation_start", f"{cursor_pos}")
        elif res == "destroyed":
            explosions.append((a.x, a.y, time.time()))
            asteroids.remove(a)
            if a.type == "good":
                score += 1
                log_event("asteroid_destroyed_good", f"score={score}")
            else:
                score //= 2
                log_event("asteroid_destroyed_bad", f"score={score}")
                if score <= 0:
                    log_event("game_over", "score<=0")
                    running = False
        else:
            a.draw(screen)

    # explosions
    for ex in explosions[:]:
        x,y,t0 = ex
        if time.time() - t0 < EXPLOSION_DURATION:
            pygame.draw.circle(screen, (255,200,0), (int(x),int(y)), 24)
        else:
            explosions.remove(ex)

    # laser glow
    if not laser_fixating:
        laser_fixating = True
        laser_start_fix = time.time()
    elif time.time() - laser_start_fix >= LASER_FIXATION_THRESHOLD:
        laser_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        pygame.draw.line(laser_surface, (0,255,0,80), LASER_ORIGIN, cursor_pos, 20)
        pygame.draw.line(laser_surface, (0,255,0,150), LASER_ORIGIN, cursor_pos, 8)
        screen.blit(laser_surface, (0,0))
        pygame.draw.line(screen, (0,255,0), LASER_ORIGIN, cursor_pos, 2)

    # cursor halo
    cursor_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    pygame.draw.circle(cursor_surface, (0,255,0,80), cursor_pos, 14)
    pygame.draw.circle(cursor_surface, (0,255,0,150), cursor_pos, 8)
    screen.blit(cursor_surface, (0,0))
    pygame.draw.circle(screen, (0,255,0), cursor_pos, 5)

    # score & timer
    score_text = font.render(f"Score: {score}", True, (255,255,255))
    screen.blit(score_text, (10,10))

    if GAME_DURATION is not None:
        remaining = max(0, int(GAME_DURATION - (time.time()-start_time)))
        timer_text = font.render(f"Time: {remaining}s", True, (255,255,255))
        screen.blit(timer_text, (WIDTH-150, 10))
        if remaining <= 0:
            log_event("game_over", "timer")
            running = False

    pygame.display.flip()

# cleanup
log_event("GAME_END", f"score={score}")
log_file.close()
if pl_device:
    try:
        #pl_device.recording_stop_and_save()
        pl_device.close()
    except Exception:
        pass
pygame.quit()
