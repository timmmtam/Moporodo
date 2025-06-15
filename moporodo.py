#!/usr/bin/env python3

import time
import subprocess
import threading
import configparser
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sys

# --- Dependency Handling ---
# Set DISPLAY environment variable for X11 if not set
if "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":0"

try:
    import pywinctl as pwc
except ImportError:
    messagebox.showerror(
        "Dependency Error",
        "pywinctl is not installed. Please run 'pip install pywinctl' to install it."
    )
    sys.exit(1)

try:
    from playsound import playsound
    PLAYSOUND_AVAILABLE = True
except ImportError:
    PLAYSOUND_AVAILABLE = False
    print("WARNING: 'playsound' library not found. Falling back to system bell for alerts.")
    print("Install it with 'pip install playsound' for custom sound support.")

# --- Main Application Class ---

class PomodoroApp:
    """A Pomodoro application that enforces focus on specific tasks."""

    def __init__(self, root_window):
        """Initialize the application."""
        self.root = root_window
        self.CONFIG_FILE = "config.ini"
        
        # --- State Variables ---
        self.game_process = None
        self.study_process = None
        self.sound_playing = False
        self.active_sound_threads = {} # Manages a thread for each alert stage sound
        self.timer_running = False
        self.stop_monitoring = threading.Event()
        self.current_phase = "Ready"
        self.time_remaining = 0
        self.alert_stage = 0
        self.monitor_thread = None
        
        # --- Default Durations ---
        self.durs = {
            "game": 25 * 60,
            "short_study": 5 * 60,
            "long_study": 30 * 60
        }

        self.alert_sounds = {}
        self.config = self.load_config()

        self.setup_gui()

    # --- Core Logic ---

    def run_pomodoro_flow(self):
        """The main logic flow for the Pomodoro cycles."""
        self.stop_monitoring.clear()
        self.timer_running = True
        
        try:
            for i in range(4):
                if self.stop_monitoring.is_set(): break
                # Game Phase
                self.current_phase = f"Game Time ({i+1}/4)"
                self.start_and_monitor(self.config.get("Settings", "game_path"), 
                                       self.config.get("Settings", "game_title"), 
                                       self.durs["game"])

                if self.stop_monitoring.is_set(): break
                # Short Study Phase
                self.current_phase = f"Study Time ({i+1}/4)"
                self.start_and_monitor(self.config.get("Settings", "study_app_path"), 
                                       self.config.get("Settings", "study_app_title"), 
                                       self.durs["short_study"])

            if not self.stop_monitoring.is_set():
                # Long Study Phase
                self.current_phase = "Long Study Session"
                self.start_and_monitor(self.config.get("Settings", "study_app_path"),
                                       self.config.get("Settings", "study_app_title"),
                                       self.durs["long_study"])

            if not self.stop_monitoring.is_set():
                self.current_phase = "All Cycles Complete"
                self.root.after(0, lambda: messagebox.showinfo("Pomodoro Complete", "All Pomodoro cycles are complete!"))

        except Exception as e:
            print(f"Error in Pomodoro session: {e}")
            self.root.after(0, lambda: messagebox.showerror("Error", f"An error occurred: {str(e)}"))
        
        self.reset_ui()

    def start_and_monitor(self, app_path, app_title, duration):
        """Helper to start an application and monitor focus on it."""
        if self.stop_monitoring.is_set(): return
        
        print(f"Starting phase: {self.current_phase}")
        self._start_application(app_path, app_title)
        time.sleep(3) # Give app time to launch/activate
        self._monitor_focus(app_title, duration)

    def _monitor_focus(self, target_title, duration_seconds):
        """Monitor focus on the target application and enforce it."""
        start_time = time.time()
        self.time_remaining = duration_seconds
        last_focus_lost_time = None
        self.alert_stage = 0

        while (time.time() - start_time) < duration_seconds and not self.stop_monitoring.is_set():
            active_window_title = self._get_active_window_title()

            if active_window_title and target_title.lower() not in active_window_title.lower():
                if last_focus_lost_time is None:
                    last_focus_lost_time = time.time()

                # Escalate alert stage every 10 seconds of lost focus
                if time.time() - last_focus_lost_time >= 10 and self.alert_stage < 5:
                    self.alert_stage += 1
                    last_focus_lost_time = time.time() # Reset timer for the next stage
                    print(f"Alert stage increased to: {self.alert_stage}")

                self._manage_alert_sounds()
                
                print(f"Focus lost! Active: '{active_window_title}' (Stage {self.alert_stage})")
            else:
                if self.sound_playing:
                    self._stop_all_sounds()
                self.alert_stage = 0
                last_focus_lost_time = None
            
            self.time_remaining = int(duration_seconds - (time.time() - start_time))
            time.sleep(1)

        self._stop_all_sounds()
        print(f"Focus monitoring ended for: {target_title}")

    # --- Sound Handling ---

    def _sound_player_loop(self, sound_path):
        """A loop to play a single sound file repeatedly. Meant to be run in a thread."""
        while self.sound_playing:
            try:
                if sound_path == "system_bell" or not PLAYSOUND_AVAILABLE:
                    self.root.bell()
                    time.sleep(1)  # System bell needs a longer pause
                else:
                    playsound(sound_path, block=True)
            except Exception as e:
                print(f"Error playing sound '{sound_path}': {e}. Falling back to system bell.")
                self.root.bell()
                time.sleep(1)  # Prevent rapid error loops

            if not self.sound_playing:
                break
            time.sleep(0.1)

    def _manage_alert_sounds(self):
        """Manages sound threads, starting new ones for each alert stage."""
        if not self.sound_playing:
            self.sound_playing = True

        for stage in range(self.alert_stage + 1):
            if stage not in self.active_sound_threads:
                sound_path = self.alert_sounds.get(f"stage_{stage}", "system_bell")
                thread = threading.Thread(target=self._sound_player_loop, args=(sound_path,), daemon=True)
                thread.start()
                self.active_sound_threads[stage] = thread
                print(f"Started sound thread for alert stage {stage}.")

    def _stop_all_sounds(self):
        """Stops all currently running sound alert threads."""
        if not self.sound_playing:
            return
        
        self.sound_playing = False  # Signal all threads to stop their loops
        
        print("Stopping all sound threads...")
        for stage, thread in self.active_sound_threads.items():
            if thread.is_alive():
                thread.join(timeout=0.2)  # Wait briefly for the thread to exit
        
        self.active_sound_threads.clear() # Clear the dictionary of threads
        print("All sound threads stopped.")


    # --- Application & Window Management ---

    def _get_active_window_title(self):
        """Get the title of the currently active window."""
        try:
            active_window = pwc.getActiveWindow()
            return active_window.title if active_window else None
        except Exception as e:
            print(f"Error getting active window: {e}")
            return None

    def _start_application(self, app_path, app_title):
        """Start an application or activate an existing instance."""
        try:
            windows = pwc.getWindowsWithTitle(app_title)
            if windows:
                windows[0].activate()
                print(f"Activated existing instance of: {app_title}")
                return
        except Exception as e:
            print(f"Could not find or activate existing window '{app_title}': {e}")

        try:
            cmd_parts = app_path.split()
            process = subprocess.Popen(cmd_parts, env=os.environ)
            if "game" in app_title.lower():
                self.game_process = process
            else:
                self.study_process = process
            print(f"Started new instance of: {app_path}")
        except Exception as e:
            print(f"Error starting application '{app_path}': {e}")
            self.root.after(0, lambda: messagebox.showerror("Execution Error", f"Failed to start: {app_path}\n\n{e}"))

    def _terminate_process(self, process):
        """Safely terminate a given subprocess."""
        if not process: return
        try:
            process.terminate()
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        except Exception as e:
            print(f"Error terminating process {process.pid}: {e}")
        return None

    # --- UI & Event Handlers ---

    def start_pomodoro_session(self):
        """UI command to start the Pomodoro session."""
        if self.timer_running:
            messagebox.showwarning("In Progress", "A Pomodoro session is already running.")
            return
            
        self.config = self.load_config() # Reload config before starting
        if not self.config.get("Settings", "game_path"):
            messagebox.showerror("Configuration Missing", "Please configure application paths first.")
            return

        self.monitor_thread = threading.Thread(target=self.run_pomodoro_flow, daemon=True)
        self.monitor_thread.start()
        self.update_timer_display()
        self.start_button.config(state=tk.DISABLED)
        self.config_button.config(state=tk.DISABLED)

    def stop_pomodoro_session(self):
        """UI command to stop the Pomodoro session."""
        if not self.timer_running: return
        
        if messagebox.askyesno("Confirm Stop", "Are you sure you want to stop the current Pomodoro session?"):
            self.stop_monitoring.set()
            self.timer_running = False
            self._stop_all_sounds()

            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=1)

            self.game_process = self._terminate_process(self.game_process)
            self.study_process = self._terminate_process(self.study_process)
            
            print("Pomodoro session stopped by user.")
            self.reset_ui()
            
    def reset_ui(self):
        """Reset the UI to its initial state."""
        self.timer_running = False
        self.time_remaining = self.durs["game"]
        self.current_phase = "Session Stopped"
        self.update_labels()
        self.start_button.config(state=tk.NORMAL)
        self.config_button.config(state=tk.NORMAL)

    def update_timer_display(self):
        """Update the timer display in the GUI every second."""
        if self.timer_running and not self.stop_monitoring.is_set():
            self.update_labels()
            self.root.after(1000, self.update_timer_display)

    def update_labels(self):
        """Update the time and phase labels."""
        minutes, seconds = divmod(self.time_remaining, 60)
        self.time_label.config(text=f"{minutes:02d}:{seconds:02d}")
        self.phase_label.config(text=self.current_phase)

    def on_closing(self):
        """Handle the window closing event."""
        self.stop_pomodoro_session()
        self.root.destroy()

    # --- Configuration ---

    def load_config(self):
        """Load configuration from the INI file."""
        config = configparser.ConfigParser()
        config.read(self.CONFIG_FILE)

        # Ensure sections and defaults exist
        if not config.has_section("Settings"):
            config.add_section("Settings")
        if not config.has_section("Sounds"):
            config.add_section("Sounds")
        if not config.has_section("Durations"):
            config.add_section("Durations")

        # Load durations
        self.durs["game"] = config.getint("Durations", "game_min", fallback=25) * 60
        self.durs["short_study"] = config.getint("Durations", "short_study_min", fallback=5) * 60
        self.durs["long_study"] = config.getint("Durations", "long_study_min", fallback=30) * 60
        self.time_remaining = self.durs["game"] # Set initial display time

        # Load sound paths
        for i in range(6):
            self.alert_sounds[f"stage_{i}"] = config.get("Sounds", f"stage_{i}", fallback="system_bell")
            
        return config

    def save_config(self, config_data):
        """Save configuration to the INI file."""
        config = configparser.ConfigParser()
        config.add_section("Settings")
        config.add_section("Sounds")
        config.add_section("Durations")

        for key, value in config_data["settings"].items():
            config.set("Settings", key, value)
        for key, value in config_data["sounds"].items():
            config.set("Sounds", key, value)
        for key, value in config_data["durations"].items():
            config.set("Durations", key, value)

        with open(self.CONFIG_FILE, "w") as configfile:
            config.write(configfile)
        
        self.load_config() # Reload config immediately
        self.update_labels() # Update timer display with new default

    # --- GUI Setup ---

    def setup_gui(self):
        """Create the main GUI for the application."""
        self.root.title("Pomodoro Focus Enforcer")
        self.root.geometry("1920x1080")
        self.root.minsize(500, 400)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        style = ttk.Style()
        style.theme_use('clam')

        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Pomodoro Focus Enforcer", font=("Arial", 20, "bold")).pack(pady=(0, 20))
        
        self.time_label = ttk.Label(main_frame, font=("Arial", 60, "bold"), foreground="darkgreen")
        self.time_label.pack(pady=10)
        
        self.phase_label = ttk.Label(main_frame, text="Ready to Start", font=("Arial", 16))
        self.phase_label.pack(pady=5)
        
        self.update_labels() # Initial call to set labels

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20)
        
        self.start_button = ttk.Button(button_frame, text="Start Pomodoro", command=self.start_pomodoro_session, style="Accent.TButton")
        self.start_button.pack(side=tk.LEFT, padx=10, ipady=10)
        
        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_pomodoro_session)
        self.stop_button.pack(side=tk.LEFT, padx=10, ipady=10)
        
        self.config_button = ttk.Button(button_frame, text="Configure", command=self.open_config_window)
        self.config_button.pack(side=tk.LEFT, padx=10, ipady=10)
        
        style.configure("Accent.TButton", font=("Arial", 12, "bold"), foreground="white", background="green")

    def open_config_window(self):
        """Open the configuration window."""
        ConfigWindow(self.root, self.config, self.save_config)

class ConfigWindow(tk.Toplevel):
    """Configuration window for the application."""

    def __init__(self, parent, config, save_callback):
        super().__init__(parent)
        self.title("Configuration")
        self.geometry("1920x1080")
        self.grab_set()

        self.config = config
        self.save_callback = save_callback
        
        # --- Variables ---
        self.vars = {
            "settings": {
                "game_path": tk.StringVar(value=config.get("Settings", "game_path", fallback="")),
                "game_title": tk.StringVar(value=config.get("Settings", "game_title", fallback="")),
                "study_app_path": tk.StringVar(value=config.get("Settings", "study_app_path", fallback="")),
                "study_app_title": tk.StringVar(value=config.get("Settings", "study_app_title", fallback="")),
            },
            "sounds": {f"stage_{i}": tk.StringVar(value=config.get("Sounds", f"stage_{i}", fallback="")) for i in range(6)},
            "durations": {
                "game_min": tk.StringVar(value=config.get("Durations", "game_min", fallback="25")),
                "short_study_min": tk.StringVar(value=config.get("Durations", "short_study_min", fallback="5")),
                "long_study_min": tk.StringVar(value=config.get("Durations", "long_study_min", fallback="30")),
            }
        }
        
        self.create_widgets()

    def create_widgets(self):
        """Create all widgets for the config window."""
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill="both", expand=True)

        self._create_section(main_frame, "Application Paths", self._create_path_widgets)
        self._create_section(main_frame, "Timer Durations (minutes)", self._create_duration_widgets)
        self._create_section(main_frame, "Alert Sounds (Optional)", self._create_sound_widgets)
        
        # --- Save/Cancel Buttons ---
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=20, fill='x')
        ttk.Button(btn_frame, text="Save & Close", command=self.save_and_close).pack(side='right', padx=5)
        ttk.Button(btn_frame, text="Test Paths", command=self.test_paths).pack(side='right', padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side='right', padx=5)

    def _create_section(self, parent, title, widget_factory):
        """Helper to create a labeled section frame."""
        frame = ttk.LabelFrame(parent, text=title, padding=10)
        frame.pack(pady=10, padx=10, fill="x")
        widget_factory(frame)

    def _create_path_widgets(self, parent):
        self._create_entry(parent, "Game Executable Path:", self.vars["settings"]["game_path"])
        self._create_entry(parent, "Game Window Title:", self.vars["settings"]["game_title"])
        self._create_entry(parent, "Study App Executable Path:", self.vars["settings"]["study_app_path"])
        self._create_entry(parent, "Study App Window Title:", self.vars["settings"]["study_app_title"])

    def _create_duration_widgets(self, parent):
        self._create_entry(parent, "Game Time:", self.vars["durations"]["game_min"])
        self._create_entry(parent, "Short Study Time:", self.vars["durations"]["short_study_min"])
        self._create_entry(parent, "Long Study Time:", self.vars["durations"]["long_study_min"])

    def _create_sound_widgets(self, parent):
        for i in range(6):
            self._create_browse_entry(parent, f"Stage {i} Sound File:", self.vars["sounds"][f"stage_{i}"])

    def _create_entry(self, parent, label_text, text_variable):
        """Helper to create a label and an entry widget."""
        frame = ttk.Frame(parent)
        frame.pack(fill='x', pady=2)
        ttk.Label(frame, text=label_text, width=25).pack(side='left')
        ttk.Entry(frame, textvariable=text_variable).pack(side='left', fill='x', expand=True)

    def _create_browse_entry(self, parent, label_text, text_variable):
        """Helper to create a label, entry, and browse button."""
        frame = ttk.Frame(parent)
        frame.pack(fill='x', pady=2)
        ttk.Label(frame, text=label_text, width=25).pack(side='left')
        entry = ttk.Entry(frame, textvariable=text_variable)
        entry.pack(side='left', fill='x', expand=True, padx=(0, 5))
        
        def browse():
            path = filedialog.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav"), ("All files", "*.*")])
            if path: text_variable.set(path)
        
        ttk.Button(frame, text="Browse...", command=browse).pack(side='left')

    def save_and_close(self):
        """Collect data from vars and call the save callback."""
        config_data = {
            "settings": {k: v.get().strip() for k, v in self.vars["settings"].items()},
            "sounds": {k: v.get().strip() for k, v in self.vars["sounds"].items()},
            "durations": {k: v.get().strip() for k, v in self.vars["durations"].items()}
        }
        self.save_callback(config_data)
        messagebox.showinfo("Success", "Configuration saved!", parent=self)
        self.destroy()

    def test_paths(self):
        """Test if the configured executable paths are valid."""
        results = []
        game_path = self.vars["settings"]["game_path"].get().strip()
        study_path = self.vars["settings"]["study_app_path"].get().strip()

        if game_path:
            if os.path.exists(game_path.split()[0]):
                results.append("✅ Game executable found.")
            else:
                results.append(f"❌ Game executable NOT found at: {game_path}")
        
        if study_path:
            if os.path.exists(study_path.split()[0]):
                results.append("✅ Study app executable found.")
            else:
                results.append(f"❌ Study app executable NOT found at: {study_path}")

        messagebox.showinfo("Path Test Results", "\n".join(results) if results else "No paths were entered to test.", parent=self)


if __name__ == "__main__":
    root = tk.Tk()
    app = PomodoroApp(root)
    root.mainloop()
