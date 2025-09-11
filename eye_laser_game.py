# Save this file as eye_laser_game.py
# Run from command line:
#   python eye_laser_game.py [--timer seconds] [--no-eyetracking] [--no_calibration]

import pygame
import random
import time
import math
import sys
import os
import csv
import json
import numpy as np
import cv2
import subprocess

# Pupil Labs
try:
    from pupil_labs.realtime_api.simple import discover_one_device
except ImportError:
    discover_one_device = None

# --- Settings ---
ASTEROID_SIZE = 100                # asteroid image size
FIXATION_HALO_MAX_RADIUS = 20      # max radius of the fixation halo
FIXATION_TIME = 1.0                 # seconds of gaze to destroy
LASER_FIXATION_THRESHOLD = 0.02    # seconds (20ms)
MIN_DISTANCE = ASTEROID_SIZE * 2   # minimum distance between asteroids
MIN_ASTEROIDS = 1
MAX_ASTEROIDS = 5
MAX_ON_SCREEN = 8
SPAWN_PROBABILITY = 0.5
ASTEROID_RANDOM_DISAPPEAR_CHANCE = 0.001
only_bad_start_time = None

# Hard-coded images in visuals folder
BACKGROUND_IMAGE_FILE = os.path.join("visuals", "background.png")
ASTEROID_IMAGE_FILE = os.path.join("visuals", "asteroid.png")

# Command-line arguments
GAME_DURATION = None
NO_EYETRACKING = "--no-eyetracking" in sys.argv
NO_CALIBRATION = "--no_calibration" in sys.argv

if len(sys.argv) > 2 and sys.argv[1] == '--timer':
    try:
        GAME_DURATION = int(sys.argv[2])
    except ValueError:
        GAME_DURATION = None

# --- Calibration integration ---
CALIB_FILE = "calibration.json"
homography = None

def load_homography():
    global homography
    try:
        with open(CALIB_FILE, "r") as f:
            data = json.load(f)
        src = np.array([p["gaze"] for p in data], dtype=np.float32)
        dst = np.array([p["adjusted"] for p in data], dtype=np.float32)
        homography, _ = cv2.findHomography(src, dst, method=0)
        print("Loaded homography from calibration.json")
    except Exception as e:
        print("Failed to load calibration:", e)
        homography = None

if not NO_CALIBRATION:
    print("Running calibration first...")
    subprocess.run([sys.executable, "calibrate.py"])
    load_homography()
else:
    load_homography()

# --- Pygame setup ---
pygame.init()
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
    pl_device = discover_one_device(max_search_duration_seconds=5)
    if pl_device:
        print("Pupil Labs device connected.")
        pl_device.recording_start()
    else:
        print("No device found, falling back to mouse.")

# --- Asteroid class ---
class Asteroid:
    def __init__(self, existing_asteroids, force_good=False):
        valid = False
        while not valid:
            self.x = random.randint(ASTEROID_SIZE, WIDTH - ASTEROID_SIZE)
            self.y = random.randint(ASTEROID_SIZE, HEIGHT - ASTEROID_SIZE)
            self.rect = pygame.Rect(self.x, self.y, ASTEROID_SIZE, ASTEROID_SIZE)
            valid = True
            for other in existing_asteroids:
                if math.hypot(self.rect.centerx - other.rect.centerx,
                              self.rect.centery - other.rect.centery) < MIN_DISTANCE:
                    valid = False
                    break
        self.fixating = False
        self.start_fix = None
        if force_good:
            self.type = 'good'
        else:
            self.type = random.choice(['good', 'bad'])

    def draw(self, screen):
        screen.blit(asteroid_img, self.rect.topleft)
        if self.fixating and self.start_fix is not None:
            elapsed = time.time() - self.start_fix
            growth = min(FIXATION_HALO_MAX_RADIUS,
                         int((elapsed / FIXATION_TIME) * FIXATION_HALO_MAX_RADIUS))
            color = (0, 255, 0) if self.type == 'good' else (255, 0, 0)
            halo_surface = pygame.Surface(
                (FIXATION_HALO_MAX_RADIUS*2, FIXATION_HALO_MAX_RADIUS*2), pygame.SRCALPHA)
            pygame.draw.circle(halo_surface, (*color, 100),
                               (FIXATION_HALO_MAX_RADIUS, FIXATION_HALO_MAX_RADIUS), growth)
            screen.blit(halo_surface, (self.rect.centerx - FIXATION_HALO_MAX_RADIUS,
                                       self.rect.centery - FIXATION_HALO_MAX_RADIUS))

    def update(self, cursor_pos):
        if self.rect.collidepoint(cursor_pos):
            if not self.fixating:
                self.fixating = True
                self.start_fix = time.time()
            elif time.time() - self.start_fix >= FIXATION_TIME:
                return True
        else:
            self.fixating = False
            self.start_fix = None
        return False

# --- Helpers ---
def spawn_asteroids(asteroids, count):
    available_space = MAX_ON_SCREEN - len(asteroids)
    for _ in range(min(count, available_space)):
        asteroids.append(Asteroid(asteroids))

def draw_explosion(screen, position, radius=30):
    pygame.draw.circle(screen, (255, 255, 0), position, radius)
    pygame.draw.circle(screen, (255, 165, 0), position, radius//2)

# --- Game Loop ---
asteroids = [Asteroid([], force_good=True)]
score = 0
running = True
end_reason = "quit by user"

laser_fixating = False
laser_start_fix = None
explosions = []
EXPLOSION_DURATION = 0.2

start_time = time.time()

while running:
    screen.blit(background_img, (0, 0))

    # --- Get gaze or mouse ---
    if pl_device:
        gaze = pl_device.receive_gaze_datum()
        if gaze and gaze.norm_pos:
            gx = gaze.norm_pos[0] * WIDTH
            gy = (1 - gaze.norm_pos[1]) * HEIGHT

            if homography is not None:
                pt = np.array([[[gx, gy]]], dtype=np.float32)
                mapped = cv2.perspectiveTransform(pt, homography)[0][0]
                gx, gy = mapped

            cursor_pos = (int(gx), int(gy))
        else:
            cursor_pos = pygame.mouse.get_pos()
    else:
        cursor_pos = pygame.mouse.get_pos()

    # --- Events ---
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
            end_reason = "quit"
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False
            end_reason = "esc_pressed"

    # Ensure at least one asteroid
    if len(asteroids) == 0:
        spawn_asteroids(asteroids, random.randint(MIN_ASTEROIDS, MAX_ASTEROIDS))

    # Update asteroids
    for asteroid in asteroids[:]:
        if random.random() < ASTEROID_RANDOM_DISAPPEAR_CHANCE:
            asteroids.remove(asteroid)
            continue

        if asteroid.update(cursor_pos):
            explosions.append((asteroid.rect.center, time.time()))
            asteroids.remove(asteroid)
            if asteroid.type == 'good':
                score += 1
                log_event("asteroid_destroyed_good", f"score={score}")
            else:
                score //= 2
                log_event("asteroid_destroyed_bad", f"score={score}")
                if score <= 0:
                    running = False
                    end_reason = "score <= 0"

            if len(asteroids) == 0 or random.random() < SPAWN_PROBABILITY:
                spawn_asteroids(asteroids, random.randint(MIN_ASTEROIDS, MAX_ASTEROIDS))
        else:
            asteroid.draw(screen)

    # --- Ensure not only bad asteroids for too long (3s) ---
    if asteroids:
        if all(a.type == 'bad' for a in asteroids):
            if only_bad_start_time is None:
                only_bad_start_time = time.time()
            elif time.time() - only_bad_start_time > 3:
                spawn_asteroids(asteroids, 1)
                asteroids[-1].type = 'good'
                only_bad_start_time = None
        else:
            only_bad_start_time = None

    # Explosions
    for explosion in explosions[:]:
        pos, t0 = explosion
        if time.time() - t0 < EXPLOSION_DURATION:
            draw_explosion(screen, pos)
        else:
            explosions.remove(explosion)

    # Laser with glow
    if not laser_fixating:
        laser_fixating = True
        laser_start_fix = time.time()
    elif time.time() - laser_start_fix >= LASER_FIXATION_THRESHOLD:
        laser_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        pygame.draw.line(laser_surface, (186, 85, 211, 80),
                         LASER_ORIGIN, cursor_pos, 15)
        pygame.draw.line(laser_surface, (148, 0, 211, 150),
                         LASER_ORIGIN, cursor_pos, 8)
        screen.blit(laser_surface, (0, 0))
        pygame.draw.line(screen, (255, 200, 255, 220),
                         LASER_ORIGIN, cursor_pos, 2)

    # Cursor halo
    cursor_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    pygame.draw.circle(cursor_surface, (186, 85, 211, 80), cursor_pos, 10)
    pygame.draw.circle(cursor_surface, (148, 0, 211, 150), cursor_pos, 6)
    screen.blit(cursor_surface, (0, 0))
    pygame.draw.circle(screen, (255, 200, 255, 220), cursor_pos, 3)

    # Score & timer
    screen.blit(font.render(f"Score: {score}", True, (255, 255, 255)), (10, 10))

    if GAME_DURATION is not None:
        elapsed_time = int(time.time() - start_time)
        remaining_time = max(0, GAME_DURATION - elapsed_time)
        screen.blit(font.render(f"Time: {remaining_time}s",
                                True, (255, 255, 255)), (WIDTH - 150, 10))
        if remaining_time <= 0:
            running = False
            end_reason = "timer_finished"

    pygame.display.flip()
    clock.tick(60)

# End game screen
screen.fill((0, 0, 0))
end_text = font.render(f"Game Over! Score: {score}", True, (255, 255, 255))
text_rect = end_text.get_rect(center=(WIDTH//2, HEIGHT//2))
screen.blit(end_text, text_rect)
pygame.display.flip()
log_event("END_REASON", end_reason)
time.sleep(3)

pygame.quit()
