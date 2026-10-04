# textual: app=LOKIUI
# ==========================================
#  L.O.K.I  ::  Neon Hacker Interface (Textual)
#  DUAL-MODE: Voice + Text
# ==========================================

import asyncio
import os
import datetime
import importlib.util
import threading
import queue
import pygame
import speech_recognition as sr
import edge_tts
import psutil
import random
import math

from textual.app import App, ComposeResult
from textual.widgets import Input, Static, Footer, Header, Log
from textual.containers import Container, Vertical, Horizontal
from textual.reactive import reactive
from textual.binding import Binding
from rich.text import Text

# ======== Import loki.py dynamically =========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOKI_path = os.path.join(BASE_DIR, "loki.py")

spec = importlib.util.spec_from_file_location("LOKI", LOKI_path)
LOKI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LOKI)

VOICE = "en-US-AvaNeural"  

# =========================================================
# AUDIO STREAMING PIPELINE WORKERS
# =========================================================
def tts_worker(text_queue, audio_queue):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    file_counter = 0
    while True:
        text = text_queue.get()
        if text is None: 
            audio_queue.put(None)
            break
        
        clean_text = text.replace("*", "").replace("#", "").strip()
        if not clean_text:
            continue
            
        file_counter += 1
        audio_file = f"temp_ui_reply_{file_counter}.mp3"
        try:
            communicate = edge_tts.Communicate(clean_text, VOICE)
            loop.run_until_complete(communicate.save(audio_file))
            audio_queue.put(audio_file)
        except Exception as e:
            pass

def audio_worker(audio_queue):
    pygame.mixer.init()
    while True:
        filepath = audio_queue.get()
        if filepath is None: 
            break
            
        try:
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
        except Exception:
            pass
        finally:
            try:
                if hasattr(pygame.mixer.music, 'unload'):
                    pygame.mixer.music.unload()
                if os.path.exists(filepath):
                    os.remove(filepath)
            except:
                pass
    pygame.mixer.quit()

# =========================================================
# UI WIDGETS
# =========================================================

class AICore(Static):
    is_active = reactive(False)
    
    def on_mount(self):
        self.set_interval(0.08, self.animate_core)
        self.frame = 0

    def animate_core(self):
        self.frame += 1
        color = "#00ff00" if self.is_active else "#00e5ff"
        state_label = "PROCESSING" if self.is_active else "ONLINE"
        
        # Cyber Ring Animation
        frames = ["◐", "◓", "◑", "◒"]
        spinner = frames[self.frame % len(frames)]
        
        core_visual = f"""
 [bold {color}]       .---.       [/bold {color}]
 [bold {color}]      /     \\      [/bold {color}]
 [bold {color}]     |   {spinner}   |     [/bold {color}]
 [bold {color}]      \\     /      [/bold {color}]
 [bold {color}]       '---'       [/bold {color}]

  STATE: [{color}]{state_label}[/{color}]
"""
        self.update(core_visual)

class TelemetryPanel(Static):
    def on_mount(self):
        self.set_interval(1.0, self.update_telemetry)

    def update_telemetry(self):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        
        def bar(pct):
            filled = int(pct / 10)
            return "█" * filled + "░" * (10 - filled)
            
        telem = f"""
[bold #00e5ff]SYSTEM LOAD[/bold #00e5ff]
CPU: [{bar(cpu)}] {cpu:.1f}%
RAM: [{bar(ram)}] {ram:.1f}%

[bold #00e5ff]NETWORK BRAIN[/bold #00e5ff]
HOST: localhost
PORT: 11434 (Ollama)
OLLAMA: LLaMA-3 8B
"""
        self.update(telem)

class ChatPanel(Static):
    def write_message(self, sender, text, color="cyan"):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted = f"[dim]{timestamp}[/dim] [bold {color}]{sender}:[/bold {color}] {text}\n"
        log = self.query_one("#chat_content", Static)
        log.update(log.renderable + formatted)
        self.scroll_end()

    def add_message(self, raw_line, color="cyan"):
        log = self.query_one("#chat_content", Static)
        log.update(log.renderable + raw_line)
        self.scroll_end()

    def replace_last(self, new_line, color="cyan"):
        log = self.query_one("#chat_content", Static)
        text_str = str(log.renderable)
        lines = text_str.rstrip("\n").split("\n")
        if lines:
            lines[-1] = new_line
            log.update("\n".join(lines) + "\n")
        else:
            log.update(new_line + "\n")
        self.scroll_end()

    def compose(self) -> ComposeResult:
        yield Static("", id="chat_content")

class LOKIUI(App):
    """Main Neon Interface for LOKI"""

    CSS = """
    Screen { background: #010103; color: #00e5ff; }
    #cyber_header { height: 1; content-align: center middle; background: #00152b; color: #00e5ff; text-style: bold; border-bottom: solid #00e5ff; }
    
    #left_panel { width: 32; border: round #00e5ff; padding: 1; height: 100%; background: #000f1e; }
    #center_panel { width: 1fr; border: round #00e5ff; padding: 0; background: #000f1e; }
    #right_panel { width: 32; border: round #00e5ff; padding: 1; height: 100%; background: #000f1e; }
    
    .panel_title { text-align: center; border-bottom: solid #00e5ff; margin-bottom: 1; color: #00e5ff; text-style: bold; }
    
    #chat { height: 1fr; padding: 1 2; overflow-y: auto; overflow-x: hidden; background: #000914; }
    #chat_content { color: #e0f7fa; padding: 0 1; }
    #typing { height: 1; color: #00e5ff; padding-left: 2; }
    #input { border: round #00e5ff; height: 3; padding: 0 1; background: #00152b; color: #ffffff; }
    
    Footer { background: #00152b; color: #00e5ff; }
    """

    BINDINGS = [
        Binding("f1", "toggle_voice", "🎙️ Jarvis Mode (Voice)", show=True),
        Binding("f2", "toggle_text", "⌨️ Silent Mode (Text)", show=True),
    ]

    is_voice_mode = reactive(False)
    is_processing = reactive(False)

    def compose(self) -> ComposeResult:
        yield Static("============ [ 0XF2A1 - SYSTEM LINK ACTIVE ] L.O.K.I PROTOCOL ============", id="cyber_header")
        with Horizontal():
            with Vertical(id="left_panel"):
                yield Static("[bold #1e90ff]AI CORE STATUS[/bold #1e90ff]", classes="panel_title")
                yield AICore(id="ai_core")

            with Vertical(id="center_panel"):
                yield ChatPanel(id="chat")
                yield Static("", id="typing")
                yield Input(placeholder="COMMAND LINE INTERFACE... (F1 for Voice)", id="input")

            with Vertical(id="right_panel"):
                yield Static("[bold #1e90ff]SYSTEM TELEMETRY[/bold #1e90ff]", classes="panel_title")
                yield TelemetryPanel(id="telemetry")
        yield Footer()

    async def on_mount(self):
        os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
        self.recognizer = sr.Recognizer()
        
        mic_idx = LOKI.profile.get("mic_device_index")
        try:
            try:
                self.mic = sr.Microphone(device_index=mic_idx)
                loop = asyncio.get_event_loop()
                def _adjust_mic():
                    with self.mic as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
                await loop.run_in_executor(None, _adjust_mic)
            except Exception as e_mic:
                self.mic = sr.Microphone(device_index=None)
                loop = asyncio.get_event_loop()
                def _adjust_mic_def():
                    with self.mic as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
                await loop.run_in_executor(None, _adjust_mic_def)
        except Exception as e:
            with open(os.path.join(BASE_DIR, "logs", "error.log"), "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now()}] Microphone Init Error: {e}\n")
            self.mic = None
            
        self.stop_listening_fn = None
        
        chat = self.query_one("#chat", ChatPanel)
        chat.write_message("System", "Activating L.O.K.I Protocol...", "cyan")
        greeting = LOKI.personality.get("greeting", "Hello, I am LOKI.")
        chat.write_message("LOKI", greeting, "#1e90ff")
        
        self.query_one("#input", Input).focus()

    def watch_is_processing(self, old_val, new_val):
        core = self.query_one("#ai_core", AICore)
        core.is_active = new_val or self.is_voice_mode

    def watch_is_voice_mode(self, old_val, new_val):
        core = self.query_one("#ai_core", AICore)
        core.is_active = new_val or self.is_processing

    # ---------- MODE TOGGLES ----------
    def action_toggle_voice(self):
        if not self.is_voice_mode:
            self.is_voice_mode = True
            self.query_one("#cyber_header", Static).update("============ [ 0XF2A1 - VOICE LINK L.O.K.I MODE ACTIVATED ] ============")
            self.start_passive_listening()
            self.query_one("#chat", ChatPanel).write_message("System", "Voice Protocol Enabled. Mic Active.", "#1e90ff")

    def action_toggle_text(self):
        if self.is_voice_mode:
            self.is_voice_mode = False
            self.query_one("#cyber_header", Static).update("============ [ 0XF2A1 - SYSTEM LINK ACTIVE ] L.O.K.I PROTOCOL ============")
            self.stop_passive_listening()
            self.query_one("#chat", ChatPanel).write_message("System", "Text Protocol Enabled. Mic Offline.", "blue")

    # ---------- VOICE LISTENER ----------
    def start_passive_listening(self):
        if self.stop_listening_fn is None and self.mic is not None:
            self.stop_listening_fn = self.recognizer.listen_in_background(self.mic, self.mic_callback)

    def stop_passive_listening(self):
        if self.stop_listening_fn is not None:
            self.stop_listening_fn(wait_for_stop=False)
            self.stop_listening_fn = None

    def mic_callback(self, recognizer, audio):
        if self.is_processing or not self.is_voice_mode:
            return
        try:
            text = recognizer.recognize_google(audio)
            if text:
                self.call_from_thread(self.trigger_chat, text)
        except sr.UnknownValueError:
            pass  # Ignore unrecognized audio
        except Exception as e:
            with open(os.path.join(BASE_DIR, "logs", "error.log"), "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now()}] Speech Recognition Error: {e}\n")

    def trigger_chat(self, msg):
        self.query_one("#input", Input).value = ""
        asyncio.create_task(self.process_input(msg))

    # ---------- INPUT HANDLER ----------
    async def on_input_submitted(self, event: Input.Submitted):
        msg = event.value.strip()
        if not msg: return
        self.query_one("#input", Input).value = ""
        await self.process_input(msg)

    async def process_input(self, msg):
        if self.is_processing: return
        self.is_processing = True

        self.stop_passive_listening()
        
        chat = self.query_one("#chat", ChatPanel)
        chat.write_message(LOKI.profile.get("user_name", "User"), msg, "cyan")

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        base_line = f"[dim]{timestamp}[/dim] [bold #1e90ff]LOKI: [/bold #1e90ff]"
        chat.add_message(base_line, "#1e90ff")
        
        self.streamed_text = ""

        def on_token(token):
            self.streamed_text += token
            self.call_from_thread(chat.replace_last, f"{base_line}{self.streamed_text}", "#1e90ff")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.ask_LOKI_worker, msg, on_token)

        self.is_processing = False
        if self.is_voice_mode:
            self.start_passive_listening()

    def ask_LOKI_worker(self, msg, token_callback):
        if self.is_voice_mode:
            text_queue = queue.Queue()
            audio_queue = queue.Queue()
            t_tts = threading.Thread(target=tts_worker, args=(text_queue, audio_queue))
            t_audio = threading.Thread(target=audio_worker, args=(audio_queue,))
            t_tts.start()
            t_audio.start()

            current_sentence = []

            def dual_callback(token):
                token_callback(token)
                current_sentence.append(token)
                token_clean = token.strip()
                if token_clean and token_clean[-1] in ".!?":
                    sentence_str = "".join(current_sentence).strip()
                    if sentence_str:
                        text_queue.put(sentence_str)
                    current_sentence.clear()

            try:
                LOKI.chat_with_LOKI(msg, token_callback=dual_callback)
            except Exception as e:
                token_callback(f"\n[Error: {e}]")

            if current_sentence:
                sentence_str = "".join(current_sentence).strip()
                if sentence_str: text_queue.put(sentence_str)

            text_queue.put(None)
            t_tts.join()
            t_audio.join()
        else:
            try:
                LOKI.chat_with_LOKI(msg, token_callback=token_callback)
            except Exception as e:
                token_callback(f"\n[Error: {e}]")

if __name__ == "__main__":
    LOKIUI().run()
