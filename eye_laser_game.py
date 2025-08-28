# Save this file as eye_laser_game.py
# Run from command line:  python eye_laser_game.py [--timer seconds]

import pygame
import random
import time
import math
import sys

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
ASTEROID_RANDOM_DISAPPEAR_CHANCE = 0.001  # chance per frame for asteroid to disappear randomly

# Timer argument (optional, named argument)
GAME_DURATION = None
if len(sys.argv) > 2 and sys.argv[1] == '--timer':
    try:
        GAME_DURATION = int(sys.argv[2])
    except ValueError:
        GAME_DURATION = None

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Eye Laser Game")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 36)

# Laser origin (bottom middle of screen)
LASER_ORIGIN = (WIDTH // 2, HEIGHT)

# --- Asteroid class with types ---
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
        self.type = random.choice(['good', 'bad'])

    def draw(self, screen):
        pygame.draw.circle(screen, (100, 100, 100), self.rect.center, ASTEROID_SIZE // 2)
        if self.fixating and self.start_fix is not None:
            elapsed = time.time() - self.start_fix
            max_radius = ASTEROID_SIZE // 2
            growth = min(max_radius, int((elapsed / FIXATION_TIME) * max_radius))
            color = (0, 255, 0) if self.type == 'good' else (255, 0, 0)
            pygame.draw.circle(screen, color, self.rect.center, growth)

    def update(self, cursor_pos):
        if self.rect.collidepoint(cursor_pos):
            if not self.fixating:
                self.fixating = True
                self.start_fix = time.time()
            else:
                if time.time() - self.start_fix >= FIXATION_TIME:
                    return True
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

# --- End game screen ---
def show_end_screen(screen, font, score):
    screen.fill((0, 0, 0))
    end_text = font.render("GAME OVER", True, (255, 0, 0))
    score_text = font.render(f"Final Score: {score}", True, (255, 255, 255))
    screen.blit(end_text, ((WIDTH - end_text.get_width()) // 2, HEIGHT // 2 - 50))
    screen.blit(score_text, ((WIDTH - score_text.get_width()) // 2, HEIGHT // 2 + 10))
    pygame.display.flip()
    pygame.time.wait(3000)

# --- Game Loop ---
asteroids = [Asteroid([])]
score = 0
running = True

laser_fixating = False
laser_start_fix = None
explosions = []
EXPLOSION_DURATION = 0.2

start_time = time.time()  # timer start

while running:
    screen.fill((0, 0, 0))
    cursor_pos = pygame.mouse.get_pos()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Ensure at least one asteroid is always present
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
            # Adjust score: green asteroids add 1, red divide by 2
            if asteroid.type == 'good':
                score += 1
            else:
                score = score // 2
                if score <= 0:
                    running = False

            if len(asteroids) == 0 or random.random() < SPAWN_PROBABILITY:
                spawn_asteroids(asteroids, random.randint(MIN_ASTEROIDS, MAX_ASTEROIDS))
        else:
            asteroid.draw(screen)

    # Draw explosions
    for explosion in explosions[:]:
        pos, start_time_exp = explosion
        if time.time() - start_time_exp < EXPLOSION_DURATION:
            draw_explosion(screen, pos)
        else:
            explosions.remove(explosion)

    # Laser
    if not laser_fixating:
        laser_fixating = True
        laser_start_fix = time.time()
    else:
        if time.time() - laser_start_fix >= LASER_FIXATION_THRESHOLD:
            laser_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            pygame.draw.line(laser_surface, (0, 255, 0, 80), LASER_ORIGIN, cursor_pos, 15)
            pygame.draw.line(laser_surface, (0, 255, 0, 150), LASER_ORIGIN, cursor_pos, 8)
            screen.blit(laser_surface, (0, 0))
            pygame.draw.line(screen, (0, 255, 0), LASER_ORIGIN, cursor_pos, 2)

    # Cursor halo
    cursor_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    pygame.draw.circle(cursor_surface, (0, 255, 0, 80), cursor_pos, 12)
    pygame.draw.circle(cursor_surface, (0, 255, 0, 150), cursor_pos, 8)
    screen.blit(cursor_surface, (0, 0))
    pygame.draw.circle(screen, (0, 255, 0), cursor_pos, 5)

    # Draw score and timer if enabled
    score_text_display = font.render(f"Score: {score}", True, (255, 255, 255))
    screen.blit(score_text_display, (10, 10))

    if GAME_DURATION is not None:
        elapsed_time = int(time.time() - start_time)
        remaining_time = max(0, GAME_DURATION - elapsed_time)
        timer_text = font.render(f"Time: {remaining_time}s", True, (255, 255, 255))
        screen.blit(timer_text, (WIDTH - 150, 10))
        if remaining_time <= 0:
            running = False

    pygame.display.flip()
    clock.tick(60)

# Show end game screen
show_end_screen(screen, font, score)
pygame.quit()
