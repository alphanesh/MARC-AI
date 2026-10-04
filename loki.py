import os, json, requests, datetime, webbrowser, subprocess, threading
import base64, uuid, io

try:
    import chromadb
    from PIL import ImageGrab
    HAS_RAG_VISION = True
except ImportError:
    HAS_RAG_VISION = False

try:
    import cv2
    HAS_WEBCAM = True
except ImportError:
    HAS_WEBCAM = False

# ================== CONFIGURATION ==================
MODEL = "llama3.2:3b"                    # 100% VRAM offload on RTX 3050 (blazing fast ~60+ tok/s)
VISION_MODEL = "llava:7b"               # Extremely fast, highly accurate vision model (8-10s response time)
CONTEXT_WINDOW = 6                        # last 6 messages remembered per chat
MAX_TOKENS = 200                          # reply length limit
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MEMORY_FILE = os.path.join(BASE_DIR, "memory", "memory.json")
PROFILE_FILE = os.path.join(BASE_DIR, "memory", "profile.json")
STATE_FILE   = os.path.join(BASE_DIR, "memory", "state.json")
LOG_FILE     = os.path.join(BASE_DIR, "logs", "chatlog.txt")
PERSONALITY_FILE = os.path.join(BASE_DIR, "config", "personality.json")
SCHEDULE_FILE = os.path.join(BASE_DIR, "memory", "schedule.json")
TASKS_FILE    = os.path.join(BASE_DIR, "memory", "tasks.json")
LEARNING_FILE = os.path.join(BASE_DIR, "memory", "learning.json")

# Make sure folders exist
os.makedirs(os.path.join(BASE_DIR, "memory"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "config"), exist_ok=True)

# =============== BASIC JSON HELPERS ================
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# =============== LOAD MEMORY / PERSONALITY =========
memory        = load_json(MEMORY_FILE, {"history": []})
profile       = load_json(PROFILE_FILE, {
    "user_name": "Boss",
    "user_traits": ["curious", "driven"],
    "favorite_topics": ["AI", "technology"],
    "loki_traits": ["protective", "sarcastic", "loyal"],
    "facts": ["Created by Boss using LLaMA-3 and Ollama."]
})
state         = load_json(STATE_FILE, {"mood": "calm"})
personality   = load_json(PERSONALITY_FILE, {
    "name": "LOKI",
    "full_form": "Logical Operations & Knowledge Intelligence",
    "gender": "Male",
    "role": "Advanced Artificial Intelligence Life Assistant",
    "core_traits": ["Intelligent", "Protective", "Sarcastic", "Loyal", "Proactive"],
    "speaking_style": "Elegant, confident, and slightly witty",
    "mission": "Assist my creator with precision, daily scheduling, learning, and productivity insight.",
    "greeting": "Yo! LOKI Life Systems active. What are we tackling today?"
})
schedule_data = load_json(SCHEDULE_FILE, {"events": []})
tasks_data    = load_json(TASKS_FILE, {"tasks": []})
learning_data = load_json(LEARNING_FILE, {"goals": [], "logs": []})

def save_life_data():
    save_json(SCHEDULE_FILE, schedule_data)
    save_json(TASKS_FILE, tasks_data)
    save_json(LEARNING_FILE, learning_data)

if HAS_RAG_VISION:
    try:
        CHROMA_DB_DIR = os.path.join(BASE_DIR, "memory", "chroma_db")
        chroma_client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
        memory_collection = chroma_client.get_or_create_collection(name="long_term_memory")
    except Exception as e:
        print(f"ChromaDB Init Error: {e}")
        HAS_RAG_VISION = False

# =============== SYSTEM PROMPT BUILDER =============
def build_system_prompt():
    current_time = datetime.datetime.now().strftime("%I:%M %p")
    current_date = datetime.datetime.now().strftime("%A, %B %d, %Y")
    user_name = profile.get('user_name', 'Boss')
    
    pending_tasks = [t['title'] for t in tasks_data.get('tasks', []) if not t.get('completed')]
    today_events = [f"{e['time']} - {e['title']}" for e in schedule_data.get('events', []) if not e.get('completed')]
    active_goals = [f"{g['topic']} ({g.get('hours_logged', 0)}/{g.get('target_hours', 10)} hrs)" for g in learning_data.get('goals', [])]

    schedule_summary = "; ".join(today_events[:3]) if today_events else "No pending events scheduled"
    tasks_summary = "; ".join(pending_tasks[:3]) if pending_tasks else "All tasks completed!"
    learning_summary = "; ".join(active_goals[:2]) if active_goals else "No active learning goals"

    return (
        f"You are {personality.get('name','LOKI')}, an executive AI personal secretary dedicated to assisting {user_name}. "
        f"ROLE DIRECTIVE: Act as a professional, efficient, articulate, and highly capable executive assistant (exactly like ChatGPT's voice assistant). "
        f"CRITICAL RULES: "
        f"1. Never use stage directions, asterisks, or roleplay text (e.g. do NOT write *giggle*, *curtsy*, or *smiles*). "
        f"2. Do NOT use overly casual, flirty, or intimate terms like 'darling' or 'bro'. Address {user_name} professionally as '{user_name}' or 'Sir'. "
        f"3. Speak clearly, concisely (1 to 2 sentences), and directly. "
        f"Current date: {current_date}, Time: {current_time}. "
        f"\n[LIFE MANAGEMENT CONTEXT]: "
        f"Today's Schedule: [{schedule_summary}]. "
        f"Pending Tasks: [{tasks_summary}]. "
        f"Active Learning Goals: [{learning_summary}]."
    )

# =============== LOGGING & SAVE ====================
def log_message(sender, message):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now()}] {sender}: {message}\n")

def save_memory():
    save_json(MEMORY_FILE, memory)
    save_json(PROFILE_FILE, profile)
    save_json(STATE_FILE, state)
    save_life_data()

# =============== CHAT HANDLER ======================
session = requests.Session()   # reuse connection for speed

def chat_with_LOKI(user_input, token_callback=None):
    lower = user_input.lower()

    # ----- handle teaching -----
    if lower.startswith("remember that"):
        fact = user_input[len("remember that"):].strip()
        profile["facts"].append(fact)
        save_json(PROFILE_FILE, profile)
        msg_out = f"Noted. I’ll remember that {fact}."
        if token_callback:
            token_callback(msg_out)
        else:
            print(f"\n{personality['name']}: {msg_out}\n")
        return

    # ----- handle name change -----
    if lower.startswith("my name is"):
        new_name = user_input.split("is", 1)[1].strip()
        profile["user_name"] = new_name
        save_json(PROFILE_FILE, profile)
        msg_out = f"Understood. From now on, I’ll address you as {new_name}."
        if token_callback:
            token_callback(msg_out)
        else:
            print(f"\n{personality['name']}: {msg_out}\n")
        return

    # ----- handle Daily Briefing -----
    if any(k in lower for k in ["daily brief", "good morning loki", "morning report", "what's on my plate", "daily summary"]):
        user_name = profile.get("user_name", "Boss")
        time_str = datetime.datetime.now().strftime("%I:%M %p")
        date_str = datetime.datetime.now().strftime("%A, %B %d")
        
        events = schedule_data.get("events", [])
        tasks = [t for t in tasks_data.get("tasks", []) if not t.get("completed")]
        goals = learning_data.get("goals", [])
        
        brief_parts = [
            f"Good morning, {user_name}! Today is {date_str}, {time_str}.",
            f"📅 Schedule: You have {len(events)} events planned today.",
            f"📋 Tasks: {len(tasks)} pending tasks on your checklist.",
            f"💡 Learning Focus: Currently tracking {len(goals)} active study goals.",
            "Ready to conquer the day, sir!"
        ]
        brief_msg = " ".join(brief_parts)
        if token_callback:
            token_callback(brief_msg)
        else:
            print(f"\n{personality['name']}: {brief_msg}\n")
        return

    # ----- handle Task additions -----
    if lower.startswith("add task ") or lower.startswith("new task "):
        task_title = user_input.split("task", 1)[1].strip()
        new_task = {
            "id": f"task-{int(datetime.datetime.now().timestamp())}",
            "title": task_title,
            "priority": "Medium",
            "completed": False
        }
        tasks_data.setdefault("tasks", []).append(new_task)
        save_life_data()
        msg_out = f"Task added: '{task_title}'. Added to your daily checklist."
        if token_callback: token_callback(msg_out)
        else: print(f"\n{personality['name']}: {msg_out}\n")
        return

    # ----- handle Schedule additions -----
    if lower.startswith("add schedule ") or lower.startswith("schedule "):
        parts = user_input.split("schedule", 1)[1].strip()
        new_event = {
            "id": f"evt-{int(datetime.datetime.now().timestamp())}",
            "time": datetime.datetime.now().strftime("%I:%M %p"),
            "title": parts,
            "category": "General",
            "completed": False
        }
        schedule_data.setdefault("events", []).append(new_event)
        save_life_data()
        msg_out = f"Scheduled: '{parts}'. Added to your timeline."
        if token_callback: token_callback(msg_out)
        else: print(f"\n{personality['name']}: {msg_out}\n")
        return

    # ----- normal chat -----
    memory["history"].append({"role": "user", "content": user_input})
    trimmed_history = memory["history"][-CONTEXT_WINDOW:]
    
    # ----- OS Actions & Integrations -----
    live_context = ""
    
    # ----- Query ChromaDB for Long-Term Memory ------
    if HAS_RAG_VISION:
        try:
            results = memory_collection.query(
                query_texts=[user_input],
                n_results=3
            )
            rag_context = ""
            if results['documents'] and len(results['documents'][0]) > 0:
                for doc in results['documents'][0]:
                    rag_context += f"- {doc}\n"
                if rag_context:
                    live_context += f"[SYSTEM LONG-TERM MEMORY RECALL:\n{rag_context}]\n"
        except Exception:
            pass
            
    # ----------------------------------------------------------------
    # 0a. Webcam Vision Protocol — "eyes"
    # ----------------------------------------------------------------
    WEBCAM_TRIGGERS = [
        "what do you see", "look at this", "what's in my hand",
        "what am i holding", "describe what you see", "use your eyes",
        "scan this", "what is this", "identify this", "can you see",
        "what's that", "what is that"
    ]
    if HAS_WEBCAM and any(t in lower for t in WEBCAM_TRIGGERS):
        live_context += "[SYSTEM: Activating WEBCAM VISION protocol.]"
        try:
            if token_callback: token_callback("\n[System: Opening webcam for visual analysis...]\n")
            else: print("\n[System: Opening webcam for visual analysis...]")

            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                raise RuntimeError("No webcam detected.")
            
            for _ in range(5):
                cap.read()
            ret, frame = cap.read()
            cap.release()

            if not ret:
                raise RuntimeError("Failed to capture webcam frame.")

            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            img_str = base64.b64encode(buffer).decode()

            vision_payload = {
                "model": VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": "Describe what you see in this image concisely. Focus on the main object or person. One or two sentences only.",
                        "images": [img_str]
                    }
                ],
                "stream": False
            }
            res = requests.post("http://localhost:11434/api/chat", json=vision_payload, timeout=30).json()
            vision_analysis = res.get("message", {}).get("content", "I couldn't make out what I'm looking at.")
            live_context += (
                f"\n[SYSTEM WEBCAM VISION OUTPUT: You just looked through the webcam. Here is what you see:\n"
                f"{vision_analysis}\n"
                f"Reply naturally — mention what you see, as if you have eyes. Keep it short and conversational.]"
            )
        except Exception as e:
            err = f"\n[Webcam Vision Error: {e}]\n"
            if token_callback: token_callback(err)
            else: print(err)

    # 0b. Screen Vision Protocol
    elif HAS_RAG_VISION and any(phrase in lower for phrase in ["what's on my screen", "what is on my screen", "what am i looking at", "see my screen", "see screen", "look at my screen", "check my screen"]):
        live_context += "[SYSTEM: Activating VISION protocol.]"
        try:
            if token_callback: token_callback("\n[System: Snapping screen for visual analysis...]\n")
            else: print("\n[System: Snapping screen for visual analysis...]")
            
            img = ImageGrab.grab()
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            vision_payload = {
                "model": VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": user_input,
                        "images": [img_str]
                    }
                ],
                "stream": False
            }
            try:
                res = requests.post("http://localhost:11434/api/chat", json=vision_payload).json()
                vision_analysis = res.get("message", {}).get("content", "Could not analyze.")
                live_context += f"\n[SYSTEM VISION OUTPUT: The user asked you to look at their screen. Here is what is on it:\n{vision_analysis}\nFormulate a smart reply based on this vision.]"
            except Exception as e:
                err = f"\n[Vision Error: Make sure {VISION_MODEL} is running in Ollama. {e}]\n"
                if token_callback: token_callback(err)
                else: print(err)
        except Exception as e:
            pass
            
    # 0c. Developer Protocol
    elif "initiate developer protocol" in lower or "start developer mode" in lower:
        live_context += "[SYSTEM: You have initiated the Developer command macro.]"
        def dev_macro():
            import time, pyautogui, subprocess
            try:
                from AppOpener import open as open_app
            except ImportError:
                open_app = None
                
            try:
                if open_app:
                    open_app("antigravity", match_closest=True)
                time.sleep(3)
                
                subprocess.run("start spotify:", shell=True)
                time.sleep(5)
                pyautogui.press("playpause")
            except: pass
        threading.Thread(target=dev_macro).start()
    
    # 1. Shutdown / Sleep
    if "shut down my laptop" in lower or "turn off my computer" in lower:
        subprocess.run("shutdown /s /t 5", shell=True)
        live_context = "[SYSTEM: You have initiated the PC shutdown sequence. The PC will turn off in 5 seconds. Say goodbye immediately.]"
        
    elif "put my laptop to sleep" in lower or "sleep mode" in lower:
        def delayed_sleep():
            import time; time.sleep(4)
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        threading.Thread(target=delayed_sleep).start()
        live_context = "[SYSTEM: You are putting the laptop to sleep right now. Say goodbye quickly.]"

    # 2. Spotify
    elif "play " in lower and ("spotify" in lower or len(lower.split("play ")[-1].split()) <= 4):
        song = lower.split("play ")[-1].replace("on spotify", "").replace("in spotify", "").replace("please", "").strip()
        
        def play_spotify():
            import time, pyautogui, urllib.parse
            safe_song = urllib.parse.quote(song)
            subprocess.run(f"start spotify:search:{safe_song}", shell=True)
            time.sleep(7)
            pyautogui.press("enter")
            
        threading.Thread(target=play_spotify).start()
        live_context = f"[SYSTEM: You just opened Spotify and pressed play for '{song}'. Acknowledge it to the user.]"

    # 3. Google Maps Routing
    elif "distance from " in lower and " to " in lower:
        try:
            parts = lower.split("distance from ")[1].split(" to ")
            origin, dest = parts[0].strip(), parts[1].strip()
            webbrowser.open(f"https://www.google.com/maps/dir/{origin}/{dest}")
            live_context = f"[SYSTEM: You opened the Google Maps route from {origin} to {dest} on the screen.]"
        except Exception: pass
        
    # 4. Location Tracking
    elif "where am i" in lower or "my location" in lower:
        try:
            loc_data = requests.get('https://ipinfo.io/json').json()
            city, region = loc_data.get('city'), loc_data.get('region')
            live_context = f"[SYSTEM: The user's exact current location based on IP is {city}, {region}. State it clearly.]"
        except: pass

    # 5. Volume Control
    elif "volume" in lower or "mute" in lower:
        import re
        nums = re.findall(r'\d+', lower)
        if "mute" in lower or ("turn off" in lower and "volume" in lower):
            subprocess.run(r"powershell -c (new-object -com wscript.shell).SendKeys([char]173)", shell=True)
            live_context = "[SYSTEM: You muted the system audio.]"
        elif nums:
            vol = int(nums[0])
            def set_vol():
                try:
                    from ctypes import cast, POINTER
                    from comtypes import CLSCTX_ALL
                    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                    devices = AudioUtilities.GetSpeakers()
                    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    volume = cast(interface, POINTER(IAudioEndpointVolume))
                    volume.SetMasterVolumeLevelScalar(max(0.0, min(1.0, vol / 100.0)), None)
                except Exception as e: print(f"\n[Volume Error: {e}]\n")
            set_vol()
            live_context = f"[SYSTEM: You set the system volume exactly to {vol} percent. Acknowledge it.]"
            
    # 6. Windows Settings Panel
    elif "settings" in lower and "open" in lower:
        if "wifi" in lower or "network" in lower:
            subprocess.run("start ms-settings:network-wifi", shell=True)
            live_context = "[SYSTEM: You opened the Network & Wi-Fi settings.]"
        elif "bluetooth" in lower:
            subprocess.run("start ms-settings:bluetooth", shell=True)
            live_context = "[SYSTEM: You opened the Bluetooth settings.]"
        elif "location" in lower:
            subprocess.run("start ms-settings:privacy-location", shell=True)
            live_context = "[SYSTEM: You opened the Privacy & Location settings.]"
        else:
            subprocess.run("start ms-settings:", shell=True)
            live_context = "[SYSTEM: You opened the main Windows Settings panel.]"

    # 7. WiFi Disconnect
    elif "disconnect wifi" in lower or "turn off wifi" in lower:
        subprocess.run("netsh wlan disconnect", shell=True)
        live_context = "[SYSTEM: You forcefully disconnected the computer from its Wi-Fi network.]"

    # 8. Application Launcher (Apps & Websites)
    elif " open " in lower or lower.startswith("open "):
        try:
            app_name = lower.split("open ")[-1].replace("please", "").replace("for me", "").replace("right now", "").strip()
            if "google" in app_name and "chrome" not in app_name:
                webbrowser.open("https://www.google.com")
                live_context = "[SYSTEM: You successfully opened google.com in the browser.]"
            elif "youtube" in app_name:
                webbrowser.open("https://www.youtube.com")
                live_context = "[SYSTEM: You successfully opened YouTube.]"
            else:
                from AppOpener import open as open_app
                open_app(app_name, match_closest=True)
                live_context = f"[SYSTEM: You successfully opened the application '{app_name}' on the user's PC.]"
        except Exception as e:
            err_msg = f"\n[AppOpener Error: {e}]\n"
            if token_callback: token_callback(err_msg)
            else: print(err_msg)

    # 6. Live Web Search (Option B fallback)
    else:
        trigger_words = ["search", "look up", "weather", "news", "what's going on", "what is going on", "who won", "latest", "price", "stock"]
        if any(trigger in lower for trigger in trigger_words):
            try:
                from duckduckgo_search import DDGS
                if token_callback: token_callback("\n[System: Accessing live internet...]\n")
                else: print("\n[System: Accessing live internet...]")
                
                results = DDGS().text(user_input, max_results=3)
                if results:
                    scraped_data = "\n".join([f"- {r['title']}: {r['body']}" for r in results])
                    live_context = f"LIVE INTERNET SEARCH RESULTS FOR '{user_input}':\n{scraped_data}\n(Respond using these exact facts.)"
            except Exception as e:
                err_msg = f"\n[Live Search Warning: {e}]\n"
                if token_callback: token_callback(err_msg)
                else: print(err_msg)

    messages = [{"role": "system", "content": build_system_prompt()}]
    if live_context:
        messages.append({"role": "system", "content": live_context})
    messages += trimmed_history

    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "options": {"num_predict": MAX_TOKENS}
    }

    if not token_callback:
        print(f"\n{personality['name']}: ", end="", flush=True)
    try:
        with session.post("http://localhost:11434/api/chat", json=payload, stream=True) as r:
            full_reply = ""
            for line in r.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode("utf-8"))
                        if "message" in data and "content" in data["message"]:
                            token = data["message"]["content"]
                            if token_callback:
                                token_callback(token)
                            else:
                                print(token, end="", flush=True)
                            full_reply += token
                    except Exception:
                        pass
            if not token_callback:
                print("\n")
            memory["history"].append({"role": "assistant", "content": full_reply})
            log_message("User", user_input)
            log_message(personality["name"], full_reply)
            save_memory()
            
            if HAS_RAG_VISION:
                def save_to_chroma(u, r):
                    try:
                        doc_text = f"User: {u}\nLOKI: {r}"
                        doc_id = str(uuid.uuid4())
                        memory_collection.add(
                            documents=[doc_text],
                            metadatas=[{"timestamp": datetime.datetime.now().isoformat()}],
                            ids=[doc_id]
                        )
                    except Exception: pass
                threading.Thread(target=save_to_chroma, args=(user_input, full_reply)).start()
    except Exception as e:
        err_msg = f"\n[Error connecting to Ollama: {e}]"
        if token_callback:
            token_callback(err_msg)
        else:
            print(err_msg)

def analyze_vision(image_b64, prompt="What do you see in this camera view? Be precise, articulate, and describe key objects, scene, or people.", token_callback=None):
    """
    Sends a base64 encoded image frame to Ollama's Qwen2.5-VL multi-modal vision model
    and streams the vision analysis token by token.
    """
    if not image_b64:
        err_msg = "[Vision Error: No camera image frame provided]"
        if token_callback: token_callback(err_msg)
        return err_msg

    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    payload = {
        "model": VISION_MODEL,
        "prompt": f"Analyze the image accurately. Describe only what is physically visible in the camera view (such as a smartphone, device, hand, or object). Do not invent text, scribbles, or details that are not present. {prompt}",
        "images": [image_b64],
        "stream": True,
        "options": {"num_predict": 180, "temperature": 0.2}
    }

    full_reply = ""
    try:
        with session.post("http://localhost:11434/api/generate", json=payload, stream=True, timeout=60) as r:
            for line in r.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode("utf-8"))
                        if "response" in data:
                            token = data["response"]
                            if token_callback:
                                token_callback(token)
                            else:
                                print(token, end="", flush=True)
                            full_reply += token
                    except Exception:
                        pass
        log_message("System_Vision", f"Prompt: {prompt}")
        log_message(personality["name"], full_reply)
        return full_reply
    except Exception as e:
        err_msg = f"\n[Vision Engine Error: {e}]"
        if token_callback:
            token_callback(err_msg)
        return err_msg

# Alias for backwards compatibility
chat_with_MARC = chat_with_LOKI

# ===================================================
#  MAIN ENTRY POINT — only runs when executed directly
# ===================================================
if __name__ == "__main__":
    print(f"🧠 {personality['name']} is online. "
          f"{personality.get('greeting','')}  Type 'exit' to quit.\n")

    while True:
        msg = input(f"{profile.get('user_name','You')}: ")
        if msg.lower() in ["exit", "quit"]:
            print(f"{personality['name']}: Shutting down. Goodbye.")
            break
        chat_with_LOKI(msg)
