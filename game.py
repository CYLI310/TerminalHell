import math
import re
import os
import json
import sys
import time
import random
import select
import termios
import tty

# Fix for macOS arrow key delay
os.environ.setdefault('ESCDELAY', '25')

# --- Configuration & Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_FILE = os.path.join(BASE_DIR, "save_data.json")
LEVELS_FILE = os.path.join(BASE_DIR, "levels.json")

# --- ANSI Escape Codes ---
CLEAR = "\033[2J"
HOME = "\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

def get_terminal_size():
    try:
        rows, cols = os.popen('stty size', 'r').read().split()
        return int(cols), int(rows)
    except:
        return 80, 24

def strip_ansi(s):
    return re.sub(r'\033\[[0-9;]*m', '', s)

class GameEngine:
    def __init__(self):
        self.save_data = self.load_save()
        self.levels = self.load_levels()
        self.width, self.height = get_terminal_size()
        self.running = True
        self.state = "MENU"
        self.current_level = self.save_data['unlocked_level']
        self.difficulty = self.save_data.get('difficulty', 'Normal')
        
        # Game objects
        self.px, self.py = 0, 0
        self.bullets = [] # Enemy bullets: [x, y, dx, dy]
        self.player_bullets = [] # Player bullets: [x, y, dx, dy]
        self.enemies = [] # Enemies: [x, y, dx, dy, hp]
        self.score = 0
        self.lives = 3
        self.iframe = 0
        self.frame = 0
        self.last_shot_frame = 0
        self.shot_cooldown = 15 # Slow attack (approx 2 shots per second at 30fps)

    def load_save(self):
        default = {"high_score": 0, "unlocked_level": 1, "difficulty": "Normal"}
        if os.path.exists(SAVE_FILE):
            try:
                with open(SAVE_FILE, 'r') as f:
                    return {**default, **json.load(f)}
            except: pass
        return default

    def save_game(self):
        with open(SAVE_FILE, 'w') as f:
            json.dump(self.save_data, f, indent=4)

    def load_levels(self):
        if os.path.exists(LEVELS_FILE):
            with open(LEVELS_FILE, 'r') as f:
                return json.load(f)
        return [{"level": 1, "goal_score": 100, "spawn_rate": 0.2, "patterns": ["vertical"]}]

    def init_level(self, level_num):
        self.width, self.height = get_terminal_size()
        self.px = self.width // 2
        self.py = self.height - 3
        self.bullets = []
        self.player_bullets = []
        self.enemies = []
        self.score = 0
        self.lives = 3
        self.iframe = 0
        self.frame = 0
        self.last_shot_frame = 0
        self.state = "PLAYING"

    def get_input(self):
        if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
            return sys.stdin.read(1)
        return None

    def draw(self):
        # Build screen buffer
        buffer = []
        buffer.append(HOME)
        
        # Create a grid of spaces
        grid = [[" " for _ in range(self.width)] for _ in range(self.height)]
        
        if self.state == "MENU":
            self.draw_menu(grid)
        elif self.state == "PLAYING":
            self.draw_game(grid)
        elif self.state == "GAMEOVER":
            self.draw_message(grid, "GAME OVER!", RED)
        elif self.state == "VICTORY":
            self.draw_message(grid, "LEVEL COMPLETE!", GREEN)

        # Convert grid to string
        output = "".join(["".join(row) for row in grid])
        sys.stdout.write(HOME + output)
        sys.stdout.flush()

    def draw_menu(self, grid):
        ascii_art = [
            r"  _____                     _             _   _   _      _ _ ",
            r" |_   _|__ _ __ _ __ ___  _(_)_ __   __ _| | | | | | ___| | |",
            r"   | |/ _ \ '__| '_ ` _ \| | | '_ \ / _` | | | |_| |/ _ \ | |",
            r"   | |  __/ |  | | | | | | | | | | | (_| | | |  _  |  __/ | |",
            r"   |_|\___|_|  |_| |_| |_|_|_|_| |_|\__,_|_| |_| |_|\___|_|_|"
        ]
        
        start_y = max(1, self.height // 6)
        for i, line in enumerate(ascii_art):
            self.put_str(grid, (self.width - len(line)) // 2, start_y + i, BOLD + YELLOW + line + RESET)

        opts = [
            f"1. Start Campaign (Level {self.save_data['unlocked_level']})",
            f"D. Difficulty: [{self.difficulty}]",
            "R. Reset Progress",
            "Q. Quit"
        ]
        for i, opt in enumerate(opts):
            self.put_str(grid, self.width//2 - 12, self.height//2 + i*2, BOLD + WHITE + opt + RESET)
        
        controls = "WASD/Arrows: Move | Z/K/SPACE: Attack | Q: Quit"
        self.put_str(grid, (self.width - len(controls)) // 2, self.height - 3, CYAN + controls + RESET)

    def draw_game(self, grid):
        # Draw Player (Thicker sprite)
        player_sprite = "[▲]"
        px_pos = int(self.px) - 1 # Center the 3-char sprite
        char = BOLD + CYAN + player_sprite + RESET
        if self.iframe > 0 and self.frame % 2 == 0:
            char = "   " # Hide during flash
            
        # Draw Boss for Level 5 (Thicker sprite)
        level_info = self.levels[min(self.current_level - 1, len(self.levels)-1)]
        if level_info['level'] == 5:
            self.put_str(grid, int(self.enemy_x)-4, int(self.enemy_y), BOLD + MAGENTA + "[[= BOSS =]]" + RESET)

        # Render player
        if 0 <= px_pos < self.width - 2:
            self.put_str(grid, px_pos, int(self.py), char)
        
        # Draw Enemy Bullets (Bold dots)
        for b in self.bullets:
            if 0 <= b[1] < self.height and 0 <= b[0] < self.width:
                self.put_str(grid, int(b[0]), int(b[1]), BOLD + RED + "·" + RESET)

        # Draw Player Bullets (Vertical bars)
        for b in self.player_bullets:
            if 0 <= b[1] < self.height and 0 <= b[0] < self.width:
                self.put_str(grid, int(b[0]), int(b[1]), BOLD + YELLOW + "¦" + RESET)

        # Draw Enemies (Small ships)
        for e in self.enemies:
            if 0 <= e[1] < self.height and 0 <= e[0] < self.width:
                self.put_str(grid, int(e[0])-1, int(e[1]), BOLD + GREEN + "<#>" + RESET)

        # Draw HUD at the bottom
        self.draw_hud(grid, level_info)

    def draw_hud(self, grid, level_info):
        hud_y = self.height - 1
        
        # HUD formatting
        diff_label = f"[{self.difficulty}]"
        progress = f"SCORE: {self.score}/{level_info['goal_score']}"
        lives_label = f"LIVES: {'❤' * self.lives}"
        stats = f" LVL: {self.current_level} | {diff_label} | {progress} | {lives_label} "
        
        # Draw a bar across the bottom
        bar = "═" * self.width
        self.put_str(grid, 0, hud_y - 1, WHITE + bar + RESET)
        
        # Center the stats on the last line
        self.put_str(grid, (self.width - len(stats)) // 2, hud_y, BOLD + WHITE + stats + RESET)

    def draw_message(self, grid, msg, color):
        self.put_str(grid, self.width//2 - len(msg)//2, self.height//2, BOLD + color + msg + RESET)
        self.put_str(grid, self.width//2 - 10, self.height//2 + 2, "Press SPACE to continue")

    def put_str(self, grid, x, y, s):
        if 0 <= y < len(grid) and 0 <= x < self.width:
            grid[y][x] = s
            # Mark subsequent cells as empty so they don't produce extra spacing
            # ANSI escape codes have 0 visual width
            visible_len = len(strip_ansi(s))
            for i in range(1, visible_len):
                if x + i < self.width:
                    grid[y][x + i] = ""

    def update(self):
        if self.state == "PLAYING":
            self.update_game()

    def update_game(self):
        self.frame += 1
        level_idx = min(self.current_level - 1, len(self.levels) - 1)
        level_info = self.levels[level_idx]
        multi = {"Easy": 0.3, "Normal": 1.0, "Hard": 1.6}[self.difficulty]
        spawn_rate = level_info['spawn_rate'] * multi
        patterns = level_info.get('patterns', ['vertical'])
        
        # Enemy Boss logic
        self.enemy_x = (self.width // 2) + math.sin(self.frame * 0.1) * (self.width // 3)
        self.enemy_y = 2
        
        # Spawn bullets (Improved for high density: allow multiple spawns per frame)
        to_spawn = int(spawn_rate)
        if random.random() < (spawn_rate - to_spawn):
            to_spawn += 1
            
        for _ in range(to_spawn):
            pattern = random.choice(patterns)
            sx = self.enemy_x if level_info['level'] >= 4 else random.randint(0, self.width-1)
            sy = self.enemy_y if level_info['level'] >= 4 else 0
            
            if pattern == "vertical":
                self.bullets.append([sx, sy, 0, 0.8 * multi])
            elif pattern == "horizontal":
                side = random.choice([0, self.width-1])
                dx = 1.2 * multi if side == 0 else -1.2 * multi
                self.bullets.append([side, random.randint(2, self.height//2), dx, 0.1])
            elif pattern == "diagonal":
                self.bullets.append([sx, sy, random.uniform(-0.8, 0.8), 0.6 * multi])
            elif pattern == "circle":
                # Balanced: Every 45 degrees
                for angle in range(0, 360, 45):
                    rad = math.radians(angle)
                    self.bullets.append([sx, sy, math.cos(rad)*0.7*multi, math.sin(rad)*0.35*multi])
            elif pattern == "spiral":
                # Tight spiral
                angle = (self.frame * 20) % 360
                rad = math.radians(angle)
                self.bullets.append([sx, sy, math.cos(rad)*0.8*multi, math.sin(rad)*0.4*multi])

        # Extra "Hell" modifier for Hard difficulty
        if self.difficulty == "Hard" and self.frame % 10 == 0:
            for _ in range(3):
                self.bullets.append([random.randint(0, self.width-1), 0, random.uniform(-0.2, 0.2), 1.5])
            
        # Update bullets
        for b in self.bullets[:]:
            b[1] += b[3] # y += dy
            b[0] += b[2] # x += dx
            
            # Collision (Adjusted for thicker hitboxes)
            if abs(b[0] - self.px) < 1.8 and abs(b[1] - self.py) < 0.8:
                if self.iframe <= 0:
                    self.lives -= 1
                    self.iframe = 45 # More i-frames
                    if self.lives <= 0:
                        self.state = "GAMEOVER"
                if b in self.bullets: self.bullets.remove(b)
            elif b[1] >= self.height or b[1] < 0 or b[0] < 0 or b[0] >= self.width:
                if b in self.bullets: self.bullets.remove(b)
                # No longer adding score for dodging bullets to focus on enemy elimination
                
        # Update Player Bullets
        for b in self.player_bullets[:]:
            b[1] += b[3] # y += dy
            b[0] += b[2] # x += dx
            
            # Check collision with enemies
            hit = False
            for e in self.enemies[:]:
                if abs(b[0] - e[0]) < 2 and abs(b[1] - e[1]) < 1:
                    e[4] -= 1 # Reduce HP
                    hit = True
                    if e[4] <= 0:
                        if e in self.enemies:
                            self.enemies.remove(e)
                            self.score += 20
                    break
            
            # Check collision with boss (if active)
            if not hit and level_info['level'] >= 5:
                if abs(b[0] - self.enemy_x) < 4 and abs(b[1] - self.enemy_y) < 2:
                    self.score += 5
                    hit = True
            
            if hit or b[1] < 0 or b[1] >= self.height or b[0] < 0 or b[0] >= self.width:
                if b in self.player_bullets: self.player_bullets.remove(b)

        # Update Enemies
        if random.random() < 0.05: # Spawn enemy occasionally
            ex = random.randint(2, self.width - 3)
            self.enemies.append([ex, 0, random.uniform(-0.1, 0.1), 0.3, 1])

        for e in self.enemies[:]:
            e[1] += e[3] # y += dy
            e[0] += e[2] # x += dx
            
            # Collision with player
            if abs(e[0] - self.px) < 1.8 and abs(e[1] - self.py) < 0.8:
                if self.iframe <= 0:
                    self.lives -= 1
                    self.iframe = 45
                    if self.lives <= 0:
                        self.state = "GAMEOVER"
                if e in self.enemies: self.enemies.remove(e)
            elif e[1] >= self.height:
                if e in self.enemies: self.enemies.remove(e)
                # Removed penalty for letting enemies pass
                
        if self.iframe > 0: self.iframe -= 1
        self.score = max(0, self.score) # Ensure score is never negative
        
        if self.score >= level_info['goal_score']:
            self.save_data['unlocked_level'] = max(self.save_data['unlocked_level'], self.current_level + 1)
            self.save_data['high_score'] = max(self.save_data['high_score'], self.score)
            self.save_game()
            self.state = "VICTORY"

def list_len(l):
    return len(l)

def main():
    # Set up terminal
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write(CLEAR + HIDE_CURSOR)
        sys.stdout.flush()
        
        engine = GameEngine()
        
        while engine.running:
            # 1. Input
            key = None
            if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                key = sys.stdin.read(1)
                if key == '\x1b': # Escape sequence
                    extra = sys.stdin.read(2)
                    key = {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left'}.get(extra, None)
            
            # 2. Logic (Simplified for stability)
            if engine.state == "MENU":
                if key in ['1', ' ']:
                    engine.current_level = engine.save_data['unlocked_level']
                    engine.init_level(engine.current_level)
                elif key in ['d', 'D']:
                    diffs = ["Easy", "Normal", "Hard"]
                    engine.difficulty = diffs[(diffs.index(engine.difficulty) + 1) % 3]
                    engine.save_data['difficulty'] = engine.difficulty
                elif key in ['r', 'R']:
                    engine.save_data['unlocked_level'] = 1
                    engine.save_game()
                elif key in ['q', 'Q']:
                    engine.running = False
            
            elif engine.state == "PLAYING":
                if key == 'q': engine.state = "MENU"
                elif key in ['w', 'up']: engine.py = max(1, engine.py - 2)
                elif key in ['s', 'down']: engine.py = min(engine.height - 2, engine.py + 2)
                elif key in ['a', 'left']: engine.px = max(1, engine.px - 4)
                elif key in ['d', 'right']: engine.px = min(engine.width - 2, engine.px + 4)
                
                # Attack logic
                if key in ['z', 'k', ' ']:
                    if engine.frame - engine.last_shot_frame >= engine.shot_cooldown:
                        # Fire a spread of 3 bullets (slowly)
                        engine.player_bullets.append([engine.px, engine.py - 1, 0, -1.0])
                        engine.last_shot_frame = engine.frame
                
                engine.update_game()
                
            elif engine.state in ["GAMEOVER", "VICTORY"]:
                if key == ' ': engine.state = "MENU"

            # 3. Draw
            # Manual grid rendering to avoid flickering
            w, h = get_terminal_size()
            grid = [[" " for _ in range(w)] for _ in range(h)]
            
            if engine.state == "MENU":
                engine.draw_menu(grid)
            elif engine.state == "PLAYING":
                engine.draw_game(grid)
            elif engine.state == "GAMEOVER":
                engine.draw_message(grid, "GAME OVER!", RED)
            elif engine.state == "VICTORY":
                engine.draw_message(grid, "LEVEL COMPLETE!", GREEN)
                
            # Flatten grid and print
            lines = []
            for row in grid:
                lines.append("".join(row))
            sys.stdout.write(HOME + "\n".join(lines))
            sys.stdout.flush()
            
            time.sleep(0.033) # ~30 FPS

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        sys.stdout.write(SHOW_CURSOR + CLEAR + HOME)
        sys.stdout.flush()

if __name__ == "__main__":
    main()