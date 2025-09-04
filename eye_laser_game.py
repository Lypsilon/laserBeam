# Save this file as eye_laser_game.py
# Run from command line:  python eye_laser_game.py [--timer seconds] [--no-eyetracking] [--windowed]

import pygame
import random
import time
import math
import sys
import os
import csv

# Pupil Labs
try:
    from pupil_labs.realtime_api.simple import discover_one_device
except ImportError:
    discover_one_device = None

# --- Settings ---
ASTEROID_SIZE = 64                # asteroid image size
FIXATION_HALO_MAX_RADIUS = 80     # max radius of the fixation halo
FIXATION_TIME = 1.0               # seconds of gaze to destroy
LASER_FIXATION_THRESHOLD = 0.02   # seconds (20ms)
MIN_DISTANCE = ASTEROID_SIZE * 2  # minimum distance between asteroids
MIN_ASTEROIDS = 1
MAX_ASTEROIDS = 5
MAX_ON_SCREEN = 8
SPAWN_PROBABILITY = 0.5
ASTEROID_RANDOM_DISAPPEAR_CHANCE = 0.001

# Glasses field of view resolution (adjust to your device)
GLASSES_WIDTH = 1920
GLASSES_HEIGHT = 1080

# Hard-coded images in visuals folder
BACKGROUND_IMAGE_FILE = os.path.join("visuals", "background.png")
ASTEROID_IMAGE_FILE = os.path.join("visuals", "asteroid.png")

# --- Command-line arguments ---
GAME_DURATION = None
NO_EYETRACKING = "--no-eyetracking" in sys.argv
WINDOWED = "--windowed" in sys.argv

if "--timer" in sys.argv:
    try:
        GAME_DURATION = int(sys.argv[sys.argv.index("--timer") + 1])
    except Exception:
        GAME_DURATION = None

pygame.init()
# Fullscreen or windowed mode
if WINDOWED:
    screen = pygame.display.set_mode((1280, 720))
else:
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
WIDTH, HEIGHT = screen.get_size()
pygame.display.set_caption("Eye Laser Game")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 36)
LASER_ORIGIN = (WIDTH // 2, HEIGHT)

# --- Load images ---
background_img = pygame.image.load(BACKGROUND_IMAGE_FILE).convert()
background_img = pygame.transform.scale(background_img, (WIDTH, HEIGHT))
asteroid_img = pygame.image.load(ASTEROID_IMAGE_FILE).convert_alpha()
asteroid_img = pygame.transform.scale(asteroid_img, (ASTEROID_SIZE, ASTEROID_SIZE))

# --- Logging setup ---
os.makedirs("logs", exist_ok=True)
log_filename = time.strftime("logs/game_%Y%m%d_%H%M%S.csv")
log_file = open(log_filename, "w", newline="", encoding="utf-8")
log_writer = csv.writer(log_file)
log_writer.writerow(["timestamp", "event", "details"])

def log_event(event, details=""):
    log_writer.writerow([time.time(), event, details])
    log_file.flush()

# --- Pupil Labs init ---
pl_device = None
if not NO_EYETRACKING and discover_one_device:
    print("Looking for Pupil Labs device...")
    pl_device = discover_one_device(max_search_duration_seconds=10)
    if pl_device:
        print("✅ Pupil Labs device connected:", pl_device)
        pl_device.recording_start()
    else:
        print("❌ No device found, falling back to mouse.")
else:
    print("No eyetracking (mouse control).")

# --- Asteroid class ---
class Asteroid:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.radius = ASTEROID_SIZE // 2
        self.spawn_time = time.time()
        self.fixation_time = 0
        self.hit = False

    def draw(self, screen):
        screen.blit(asteroid_img, (self.x - self.radius, self.y - self.radius))

# --- Game state ---
asteroids = []
score = 0
running = True
start_time = time.time()
cursor_pos = (WIDTH // 2, HEIGHT // 2)
end_reason = "QUIT"

# --- Main loop ---
while running:
    dt = clock.tick(60) / 1000.0
    screen.blit(background_img, (0, 0))

    # --- Handle events ---
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
            end_reason = "QUIT"
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
                end_reason = "ESC"

    # --- Get cursor position from eyetracker or mouse ---
    if pl_device and not NO_EYETRACKING:
        try:
            gaze_sample = pl_device.receive_gaze_datum()
            if gaze_sample is not None and hasattr(gaze_sample, "x") and hasattr(gaze_sample, "y"):
                # Map glasses coordinates to game window
                mapped_x = int(gaze_sample.x / GLASSES_WIDTH * WIDTH)
                mapped_y = int(gaze_sample.y / GLASSES_HEIGHT * HEIGHT)
                mapped_x = max(0, min(WIDTH - 1, mapped_x))
                mapped_y = max(0, min(HEIGHT - 1, mapped_y))
                cursor_pos = (mapped_x, mapped_y)
            else:
                cursor_pos = pygame.mouse.get_pos()
        except Exception as e:
            print("Gaze error:", e)
            cursor_pos = pygame.mouse.get_pos()
    else:
        cursor_pos = pygame.mouse.get_pos()

    # --- Spawn asteroids ---
    if len(asteroids) < MAX_ON_SCREEN and random.random() < SPAWN_PROBABILITY:
        x = random.randint(ASTEROID_SIZE, WIDTH - ASTEROID_SIZE)
        y = random.randint(ASTEROID_SIZE, HEIGHT // 2)
        asteroids.append(Asteroid(x, y))

    # --- Draw asteroids and handle fixation ---
    for asteroid in asteroids[:]:
        asteroid.draw(screen)
        dist = math.hypot(cursor_pos[0] - asteroid.x, cursor_pos[1] - asteroid.y)
        if dist < asteroid.radius:
            asteroid.fixation_time += dt
            halo_radius = int((asteroid.fixation_time / FIXATION_TIME) * FIXATION_HALO_MAX_RADIUS)
            pygame.draw.circle(screen, (0, 255, 0), cursor_pos, halo_radius, 3)
            if asteroid.fixation_time >= FIXATION_TIME:
                asteroids.remove(asteroid)
                score += 1
                log_event("ASTEROID_DESTROYED", f"score={score}")
        else:
            asteroid.fixation_time = 0

    # --- Draw laser ---
    pygame.draw.line(screen, (255, 0, 0), LASER_ORIGIN, cursor_pos, 2)

    # --- Draw score ---
    score_text = font.render(f"Score: {score}", True, (255, 255, 255))
    screen.blit(score_text, (10, 10))

    # --- Check timer ---
    if GAME_DURATION and (time.time() - start_time) >= GAME_DURATION:
        running = False
        end_reason = "TIMER"

    pygame.display.flip()

# --- Cleanup ---
end_time = time.time()
game_duration = end_time - start_time
log_event("GAME_END", f"reason={end_reason}, duration={game_duration:.2f}s, score={score}")
log_file.close()
if pl_device:
    pl_device.recording_stop_and_save()
    pl_device.close()
pygame.quit()