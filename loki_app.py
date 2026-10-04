import webview
import threading
import queue
import asyncio
import websockets
import http.server
import socketserver
import os
import time
import datetime
import speech_recognition as sr
import edge_tts
import pygame
import json
import importlib.util

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOKI_path = os.path.join(BASE_DIR, "loki.py")
spec = importlib.util.spec_from_file_location("LOKI", LOKI_path)
LOKI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LOKI)
VOICE = "en-US-AvaNeural"

# --- WEBSOCKET SERVER LOGIC ---
connected_clients = set()
ws_loop = None

async def ws_handler(websocket):
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                mtype = data.get("type")
                if mtype == "message":
                    api.send_message(data["data"])
                elif mtype == "interrupt":
                    api.interrupt_speech()
                elif mtype == "toggle_voice":
                    api.toggle_voice(data["data"])
                elif mtype == "get_life_data":
                    life_payload = api.get_life_data()
                    await websocket.send(json.dumps({"type": "life_data", "data": life_payload}))
                elif mtype == "add_task":
                    api.add_task(data.get("title", ""), data.get("priority", "Medium"))
                elif mtype == "toggle_task":
                    api.toggle_task(data.get("id"))
                elif mtype == "add_schedule":
                    api.add_schedule_event(data.get("time", ""), data.get("title", ""))
                elif mtype == "analyze_vision":
                    api.analyze_vision(data.get("image"), data.get("prompt", "What do you see in this camera view?"))
            except Exception as e:
                print(f"WS error: {e}")
    finally:
        connected_clients.remove(websocket)

async def ws_main():
    async with websockets.serve(ws_handler, "0.0.0.0", 8765, max_size=10*1024*1024):
        print("L.O.K.I WiFi Brain Active on ws://0.0.0.0:8765")
        await asyncio.Future()  # run forever

def start_ws_server():
    global ws_loop
    ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ws_loop)
    ws_loop.run_until_complete(ws_main())

def broadcast_to_clients(data):
    if ws_loop and connected_clients:
        for ws in list(connected_clients):
            try:
                asyncio.run_coroutine_threadsafe(ws.send(json.dumps(data)), ws_loop)
            except Exception:
                pass

# --- HTTP SERVER LOGIC ---
def start_http_server():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass 
        def do_GET(self):
            if self.path == '/':
                self.path = '/loki_ui.html'
            return super().do_GET()
            
    os.chdir(BASE_DIR)
    try:
        with socketserver.TCPServer(("", 8000), Handler) as httpd:
            print("L.O.K.I Interface serving on http://0.0.0.0:8000")
            httpd.serve_forever()
    except Exception as e:
        print(f"HTTP Server error: {e}")

# --- AUDIO WORKERS ---
# --- AUDIO WORKERS ---
def tts_worker(text_queue, audio_queue, api_instance):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    file_counter = 0
    while True:
        if api_instance._is_interrupted:
            audio_queue.put(None)
            break
        try:
            text = text_queue.get(timeout=0.1)
        except queue.Empty:
            continue
            
        if text is None or api_instance._is_interrupted:
            audio_queue.put(None)
            break
            
        clean_text = text.replace("*", "").replace("#", "").strip()
        if not clean_text: continue
        file_counter += 1
        audio_file = os.path.join(BASE_DIR, f"temp_ui_reply_{file_counter}.mp3")
        try:
            communicate = edge_tts.Communicate(clean_text, VOICE)
            loop.run_until_complete(communicate.save(audio_file))
            if not api_instance._is_interrupted:
                audio_queue.put(audio_file)
            else:
                if os.path.exists(audio_file):
                    try: os.remove(audio_file)
                    except Exception: pass
        except Exception as e:
            print(f"TTS Worker Error: {e}")

def audio_worker(audio_queue, api_instance):
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
    except Exception as e:
        print(f"Pygame mixer init error: {e}")
        
    while True:
        if api_instance._is_interrupted:
            break
        try:
            filepath = audio_queue.get(timeout=0.1)
        except queue.Empty:
            continue
            
        if filepath is None or api_instance._is_interrupted:
            if filepath and os.path.exists(filepath):
                try: os.remove(filepath)
                except Exception: pass
            break
            
        try:
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if api_instance._is_interrupted:
                    pygame.mixer.music.stop()
                    break
                pygame.time.Clock().tick(10)
        except Exception as e:
            print(f"Audio Worker Error: {e}")
        finally:
            try:
                if hasattr(pygame.mixer.music, 'unload'):
                    pygame.mixer.music.unload()
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception:
                pass
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass

def find_best_microphone():
    """Uses default system sound mapper (device_index=None) to avoid PyAudio Windows sample rate host errors (-9999)."""
    print("Using Default System Sound Mapper (device_index=None) for AirPods / System Input.")
    return None

def capture_webcam_frame_b64():
    """Captures a single image frame from system webcam using OpenCV and encodes it to base64."""
    try:
        import cv2
        import base64
        for dev_idx in [0, 1]:
            cap = cv2.VideoCapture(dev_idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(dev_idx)
            if cap.isOpened():
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None:
                    ret_enc, buffer = cv2.imencode('.jpg', frame)
                    if ret_enc:
                        return base64.b64encode(buffer).decode('utf-8')
        return None
    except Exception as e:
        print(f"Webcam OpenCV Capture Error: {e}")
        return None

# --- PYWEBVIEW API ---
import time

def is_self_echo(user_text, last_ai_text):
    if not user_text or not last_ai_text:
        return False
    u_clean = "".join(c.lower() for c in user_text if c.isalnum() or c.isspace()).strip()
    a_clean = "".join(c.lower() for c in last_ai_text if c.isalnum() or c.isspace()).strip()
    if not u_clean or not a_clean:
        return False
    if u_clean == a_clean or u_clean in a_clean or a_clean in u_clean:
        return True
    u_words = set(u_clean.split())
    a_words = set(a_clean.split())
    if not u_words:
        return False
    overlap = len(u_words.intersection(a_words)) / float(len(u_words))
    return overlap > 0.6

class Api:
    def __init__(self):
        self._window = None
        self._is_voice_mode = False
        self._is_processing = False
        self._is_interrupted = False
        self._recognizer = None
        self._mic = None
        self._stop_listening_fn = None
        self._last_ai_response = ""
    
    def _escape(self, text):
        return json.dumps(text)

    def set_window(self, window):
        self._window = window

    def interrupt_speech(self):
        print("[Interrupt] Signal received. Halting audio & response immediately.")
        self._is_interrupted = True
        try:
            pygame.mixer.music.stop()
            if hasattr(pygame.mixer.music, 'unload'):
                pygame.mixer.music.unload()
        except Exception:
            pass

        if hasattr(self, '_active_text_queue') and self._active_text_queue:
            while not self._active_text_queue.empty():
                try: self._active_text_queue.get_nowait()
                except Exception: break
        if hasattr(self, '_active_audio_queue') and self._active_audio_queue:
            while not self._active_audio_queue.empty():
                try:
                    f = self._active_audio_queue.get_nowait()
                    if f and os.path.exists(f):
                        try: os.remove(f)
                        except Exception: pass
                except Exception: break

        if self._window:
            self._window.evaluate_js("window.onInterrupted()")
        broadcast_to_clients({"type": "interrupted"})

    def get_life_data(self):
        payload = {
            "schedule": LOKI.schedule_data.get("events", []),
            "tasks": LOKI.tasks_data.get("tasks", []),
            "learning": LOKI.learning_data.get("goals", [])
        }
        return payload

    def add_task(self, title, priority="Medium"):
        if not title: return
        new_task = {
            "id": f"task-{int(time.time())}",
            "title": title,
            "priority": priority,
            "completed": False
        }
        LOKI.tasks_data.setdefault("tasks", []).append(new_task)
        LOKI.save_life_data()
        self.notify_life_data_update()

    def toggle_task(self, task_id):
        tasks = LOKI.tasks_data.get("tasks", [])
        for t in tasks:
            if t.get("id") == task_id:
                t["completed"] = not t.get("completed", False)
                break
        LOKI.save_life_data()
        self.notify_life_data_update()

    def add_schedule_event(self, time_str, title):
        if not title: return
        new_evt = {
            "id": f"evt-{int(time.time())}",
            "time": time_str if time_str else datetime.datetime.now().strftime("%I:%M %p"),
            "title": title,
            "category": "General",
            "completed": False
        }
        LOKI.schedule_data.setdefault("events", []).append(new_evt)
        LOKI.save_life_data()
        self.notify_life_data_update()

    def notify_life_data_update(self):
        life_payload = self.get_life_data()
        if self._window:
            self._window.evaluate_js(f"window.updateLifeData({json.dumps(life_payload)})")
        broadcast_to_clients({"type": "life_data", "data": life_payload})

    def toggle_voice(self, active):
        self._is_voice_mode = active
        status_text = "STATUS: VOICE ACTIVE - SPEAK NOW" if active else "STATUS: ONLINE"
        
        # Update Webview & Wifi clients
        if self._window:
            self._window.evaluate_js(f"window.updateStatus({self._escape(status_text)})")
        broadcast_to_clients({"type": "status", "data": status_text})
        
        if self._is_voice_mode:
            def init_mic_worker():
                try:
                    self.stop_passive_listening()
                    print("Initializing fresh microphone instance for LOKI...")
                    recognizer = sr.Recognizer()
                    recognizer.energy_threshold = 250
                    recognizer.dynamic_energy_threshold = True
                    recognizer.dynamic_energy_adjustment_damping = 0.15
                    recognizer.dynamic_energy_ratio = 1.2
                    recognizer.pause_threshold = 0.8
                    
                    mic_idx = find_best_microphone()
                    mic = None
                    try:
                        mic = sr.Microphone(device_index=mic_idx)
                        with mic as source:
                            recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        if recognizer.energy_threshold > 500:
                            recognizer.energy_threshold = 300
                        print(f"Microphone initialized successfully (energy_threshold={recognizer.energy_threshold:.1f}).")
                    except Exception as e_mic:
                        print(f"Selected mic index {mic_idx} failed ({e_mic}). Falling back to default system microphone...")
                        mic = sr.Microphone(device_index=None)
                        with mic as source:
                            recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        recognizer.energy_threshold = 300
                    
                    self._recognizer = recognizer
                    self._mic = mic
                    
                    if self._is_voice_mode:
                        self._stop_listening_fn = self._recognizer.listen_in_background(
                            self._mic, self.mic_callback, phrase_time_limit=10
                        )
                        active_status = "STATUS: VOICE ACTIVE - SPEAK NOW"
                        print(active_status)
                        if self._window:
                            self._window.evaluate_js(f"window.updateStatus({self._escape(active_status)})")
                        broadcast_to_clients({"type": "status", "data": active_status})
                except Exception as e:
                    print(f"Microphone initialization failed: {e}")
                    self._mic = None
                    self._recognizer = None
                    self._is_voice_mode = False
                    err_status = "STATUS: ERROR - NO MIC"
                    if self._window:
                        self._window.evaluate_js(f"window.updateStatus({self._escape(err_status)})")
                    broadcast_to_clients({"type": "status", "data": err_status})

            threading.Thread(target=init_mic_worker, daemon=True).start()
        else:
            print("Voice mode deactivated.")
            self.stop_passive_listening()

    def start_passive_listening(self):
        if self._stop_listening_fn is None and self._recognizer and self._mic:
            self._stop_listening_fn = self._recognizer.listen_in_background(self._mic, self.mic_callback, phrase_time_limit=10)

    def stop_passive_listening(self):
        if self._stop_listening_fn is not None:
            try:
                self._stop_listening_fn(wait_for_stop=False)
            except Exception:
                pass
            self._stop_listening_fn = None
        self._mic = None

    def mic_callback(self, recognizer, audio):
        if not self._is_voice_mode:
            return
        try:
            text = recognizer.recognize_google(audio)
            if text:
                if is_self_echo(text, self._last_ai_response):
                    print(f"[Echo] Discarded self-echo input: '{text}'")
                    return
                print(f"[Mic] Heard: {text}")
                if self._is_processing:
                    print("[Interrupt] Interrupted LOKI playback for new user speech!")
                    self.interrupt_speech()
                    time.sleep(0.15)
                
                # Update Webview
                if self._window:
                    self._window.evaluate_js(f"window.receiveUserSpeech({self._escape(text)})")
                
                # Update Wifi Clients
                broadcast_to_clients({"type": "speech", "data": text})
                
                threading.Thread(target=self.process_message, args=(text,)).start()
        except sr.UnknownValueError:
            pass  # Unrecognized silence/noise
        except Exception as e:
            print(f"Speech Recognition error: {e}")

    def send_message(self, message):
        if is_self_echo(message, self._last_ai_response):
            print(f"[Echo] Discarded self-echo message: '{message}'")
            return
        if self._is_processing:
            self.interrupt_speech()
            time.sleep(0.15)
            
        lower_msg = message.lower()
        vision_triggers = ["what do you see", "scan room", "scan the room", "look at this", "what is in front of", "take a picture", "take photo", "analyze camera", "see this"]
        if any(trig in lower_msg for trig in vision_triggers):
            self.analyze_vision(None, prompt=message)
        else:
            threading.Thread(target=self.process_message, args=(message,)).start()

    def process_message(self, msg):
        self._is_interrupted = False
        self._is_processing = True

        # Temporarily stop mic listening while AI speaks to avoid self-echo loop
        if self._is_voice_mode:
            self.stop_passive_listening()

        text_queue = queue.Queue()
        audio_queue = queue.Queue()
        self._active_text_queue = text_queue
        self._active_audio_queue = audio_queue
        
        t_tts = None
        t_audio = None
        if self._is_voice_mode:
            t_tts = threading.Thread(target=tts_worker, args=(text_queue, audio_queue, self), daemon=True)
            t_audio = threading.Thread(target=audio_worker, args=(audio_queue, self), daemon=True)
            t_tts.start()
            t_audio.start()

        current_sentence = []
        full_ai_reply_tokens = []

        def on_token(token):
            if self._is_interrupted: return
            full_ai_reply_tokens.append(token)
            # Update Webview
            if self._window:
                self._window.evaluate_js(f"window.appendToken({self._escape(token)})")
                
            # Update Wifi Clients
            broadcast_to_clients({"type": "token", "data": token})
            
            if self._is_voice_mode:
                current_sentence.append(token)
                token_clean = token.strip()
                if token_clean and token_clean[-1] in ".!?":
                    sentence_str = "".join(current_sentence).strip()
                    if sentence_str and not self._is_interrupted:
                        text_queue.put(sentence_str)
                    current_sentence.clear()

        try:
            LOKI.chat_with_LOKI(msg, token_callback=on_token)
        except Exception as e:
            err_msg = f"\n[Error: {e}]"
            if self._window:
                self._window.evaluate_js(f"window.appendToken({self._escape(err_msg)})")
            broadcast_to_clients({"type": "token", "data": err_msg})

        self._last_ai_response = "".join(full_ai_reply_tokens).strip()

        if self._is_voice_mode and not self._is_interrupted:
            if current_sentence:
                sentence_str = "".join(current_sentence).strip()
                if sentence_str: text_queue.put(sentence_str)
            text_queue.put(None)
            if t_tts: t_tts.join()
            if t_audio: t_audio.join()

        # Signal completion if not interrupted
        if not self._is_interrupted:
            if self._window:
                self._window.evaluate_js("window.finishMessage()")
            broadcast_to_clients({"type": "finish"})

        self._is_processing = False

        # Resume mic listening after AI finishes speaking
        if self._is_voice_mode and not self._is_interrupted:
            self.start_passive_listening()

    def analyze_vision(self, image_b64=None, prompt="What do you see in this camera view? Be precise, describe key objects, people, or scene."):
        if self._is_processing:
            self.interrupt_speech()
            time.sleep(0.15)
        threading.Thread(target=self.process_vision_message, args=(image_b64, prompt), daemon=True).start()

    def process_vision_message(self, image_b64, prompt):
        self._is_interrupted = False
        self._is_processing = True

        if self._is_voice_mode:
            self.stop_passive_listening()

        if not image_b64:
            print("Capturing frame via OpenCV webcam fallback...")
            image_b64 = capture_webcam_frame_b64()

        if not image_b64:
            err_text = "[Vision Error: Unable to access camera stream or capture frame]"
            if self._window:
                self._window.evaluate_js(f"window.appendToken({self._escape(err_text)})")
                self._window.evaluate_js("window.finishMessage()")
            broadcast_to_clients({"type": "token", "data": err_text})
            broadcast_to_clients({"type": "finish"})
            self._is_processing = False
            return

        text_queue = queue.Queue()
        audio_queue = queue.Queue()
        self._active_text_queue = text_queue
        self._active_audio_queue = audio_queue
        
        t_tts = threading.Thread(target=tts_worker, args=(text_queue, audio_queue, self), daemon=True)
        t_audio = threading.Thread(target=audio_worker, args=(audio_queue, self), daemon=True)
        t_tts.start()
        t_audio.start()

        current_sentence = []
        full_ai_reply_tokens = []

        def on_token(token):
            if self._is_interrupted: return
            full_ai_reply_tokens.append(token)
            if self._window:
                self._window.evaluate_js(f"window.appendToken({self._escape(token)})")
            broadcast_to_clients({"type": "token", "data": token})
            
            current_sentence.append(token)
            token_clean = token.strip()
            if token_clean and token_clean[-1] in ".!?":
                sentence_str = "".join(current_sentence).strip()
                if sentence_str and not self._is_interrupted:
                    text_queue.put(sentence_str)
                current_sentence.clear()

        try:
            LOKI.analyze_vision(image_b64, prompt=prompt, token_callback=on_token)
        except Exception as e:
            err_msg = f"\n[Vision Engine Error: {e}]"
            if self._window:
                self._window.evaluate_js(f"window.appendToken({self._escape(err_msg)})")
            broadcast_to_clients({"type": "token", "data": err_msg})

        self._last_ai_response = "".join(full_ai_reply_tokens).strip()

        if not self._is_interrupted:
            if current_sentence:
                sentence_str = "".join(current_sentence).strip()
                if sentence_str: text_queue.put(sentence_str)
            text_queue.put(None)
            t_tts.join()
            t_audio.join()

        if not self._is_interrupted:
            if self._window:
                self._window.evaluate_js("window.finishMessage()")
            broadcast_to_clients({"type": "finish"})

        self._is_processing = False

        if self._is_voice_mode and not self._is_interrupted:
            self.start_passive_listening()

api = Api()

def ensure_ollama_service():
    import urllib.request
    try:
        req = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.5)
        if req.status == 200:
            print("Ollama engine connection verified.")
            return
    except Exception:
        pass
    print("Starting Ollama background engine...")
    import subprocess
    try:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Could not auto-start Ollama: {e}")

if __name__ == '__main__':
    os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
    ensure_ollama_service()
    
    # Start background servers
    threading.Thread(target=start_http_server, daemon=True).start()
    threading.Thread(target=start_ws_server, daemon=True).start()
    
    # Start Desktop UI with fallback server loop
    try:
        html_path = os.path.join(BASE_DIR, 'loki_ui.html')
        window = webview.create_window('L.O.K.I Desktop System', html_path, js_api=api, width=1000, height=800, background_color='#010103')
        api.set_window(window)
        webview.start()
    except Exception as e:
        print(f"PyWebView notice: {e}. Keeping HTTP & WebSocket servers live.")
        while True:
            time.sleep(1)

