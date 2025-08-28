# Save this file as eye_laser_game.py
# Run from command line:  python eye_laser_game.py

import pygame
import random
import time
import math

# --- Settings ---
WIDTH, HEIGHT = 800, 600
ASTEROID_SIZE = 40
FIXATION_TIME = 1.0  # seconds of gaze to destroy
LASER_FIXATION_THRESHOLD = 0.02  # seconds (20ms)
MIN_DISTANCE = ASTEROID_SIZE * 2  # minimum distance between asteroids
MIN_ASTEROIDS = 1
MAX_ASTEROIDS = 5
MAX_ON_SCREEN = 8
SPAWN_PROBABILITY = 0.5  # probability that destroying an asteroid spawns new ones

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Eye Laser Game")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 36)

# Laser origin (bottom middle of screen)
LASER_ORIGIN = (WIDTH // 2, HEIGHT)

# --- Asteroid class ---
class Asteroid:
    def __init__(self, existing_asteroids):
        valid = False
        while not valid:
            self.x = random.randint(ASTEROID_SIZE, WIDTH - ASTEROID_SIZE)
            self.y = random.randint(ASTEROID_SIZE, HEIGHT - ASTEROID_SIZE)
            self.rect = pygame.Rect(self.x, self.y, ASTEROID_SIZE, ASTEROID_SIZE)
            valid = True
            for other in existing_asteroids:
                dx = self.rect.centerx - other.rect.centerx
                dy = self.rect.centery - other.rect.centery
                dist = math.hypot(dx, dy)
                if dist < MIN_DISTANCE:
                    valid = False
                    break
        self.fixating = False
        self.start_fix = None

    def draw(self, screen):
        # Base asteroid color
        pygame.draw.circle(screen, (100, 100, 100), self.rect.center, ASTEROID_SIZE // 2)
        # If fixating, draw a growing red circle proportional to fixation time
        if self.fixating and self.start_fix is not None:
            elapsed = time.time() - self.start_fix
            max_radius = ASTEROID_SIZE // 2
            growth = min(max_radius, int((elapsed / FIXATION_TIME) * max_radius))
            pygame.draw.circle(screen, (255, 0, 0), self.rect.center, growth)

    def update(self, cursor_pos):
        if self.rect.collidepoint(cursor_pos):
            if not self.fixating:
                self.fixating = True
                self.start_fix = time.time()
            else:
                if time.time() - self.start_fix >= FIXATION_TIME:
                    return True  # Destroy asteroid
        else:
            self.fixating = False
            self.start_fix = None
        return False

# --- Helper function to spawn asteroids ---
def spawn_asteroids(asteroids, count):
    available_space = MAX_ON_SCREEN - len(asteroids)
    count = min(count, available_space)
    for _ in range(count):
        asteroids.append(Asteroid(asteroids))

# --- Explosion effect ---
def draw_explosion(screen, position, radius=30):
    pygame.draw.circle(screen, (255, 255, 0), position, radius)
    pygame.draw.circle(screen, (255, 165, 0), position, radius//2)

# --- Game Loop ---
asteroids = [Asteroid([])]  # start with only one asteroid
score = 0
running = True

# Variables for general fixation detection (not tied to asteroid)
laser_fixating = False
laser_start_fix = None

explosions = []  # list to store explosion effects with timestamps
EXPLOSION_DURATION = 0.2  # seconds

while running:
    screen.fill((0, 0, 0))
    cursor_pos = pygame.mouse.get_pos()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Update and draw asteroids
    for asteroid in asteroids[:]:
        if asteroid.update(cursor_pos):
            explosions.append((asteroid.rect.center, time.time()))
            asteroids.remove(asteroid)
            score += 1
            # Ensure at least one asteroid is present after destruction
            if len(asteroids) == 0 or random.random() < SPAWN_PROBABILITY:
                new_count = random.randint(MIN_ASTEROIDS, MAX_ASTEROIDS)
                spawn_asteroids(asteroids, new_count)
        else:
            asteroid.draw(screen)

    # Draw explosions
    for explosion in explosions[:]:
        pos, start_time = explosion
        if time.time() - start_time < EXPLOSION_DURATION:
            draw_explosion(screen, pos)
        else:
            explosions.remove(explosion)

    # Detect if cursor is stable enough to count as fixation for laser
    if not laser_fixating:
        laser_fixating = True
        laser_start_fix = time.time()
    else:
        if time.time() - laser_start_fix >= LASER_FIXATION_THRESHOLD:
            # Draw laser beam with halo using a transparent surface
            laser_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            pygame.draw.line(laser_surface, (0, 255, 0, 80), LASER_ORIGIN, cursor_pos, 15)  # halo
            pygame.draw.line(laser_surface, (0, 255, 0, 150), LASER_ORIGIN, cursor_pos, 8)   # inner halo
            screen.blit(laser_surface, (0, 0))
            # Draw core beam
            pygame.draw.line(screen, (0, 255, 0), LASER_ORIGIN, cursor_pos, 2)

    # Draw cursor (as a small circle = gaze) with halo
    cursor_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    pygame.draw.circle(cursor_surface, (0, 255, 0, 80), cursor_pos, 12)  # outer halo
    pygame.draw.circle(cursor_surface, (0, 255, 0, 150), cursor_pos, 8)  # inner halo
    screen.blit(cursor_surface, (0, 0))
    pygame.draw.circle(screen, (0, 255, 0), cursor_pos, 2)  # core

    # Draw score
    score_text = font.render(f"Score: {score}", True, (255, 255, 255))
    screen.blit(score_text, (10, 10))

    pygame.display.flip()
    clock.tick(60)


# pygame.quit()