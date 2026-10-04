import os
import asyncio
import pygame
import speech_recognition as sr
import edge_tts
import loki
import threading
import queue

VOICE = "en-US-AvaNeural"  # Professional, natural ChatGPT Voice style female neural voice

# ===================================================================
# PIPELINE WORKERS FOR SIMULTANEOUS STREAMING
# ===================================================================

def tts_worker(text_queue, audio_queue, state):
    """Watches for full sentences, synthesizes them, and passes them to audio player."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    file_counter = 0
    while True:
        if state.get("interrupted"):
            audio_queue.put(None)
            break
        try:
            text = text_queue.get(timeout=0.1)
        except queue.Empty:
            continue
            
        if text is None or state.get("interrupted"):
            audio_queue.put(None)
            break
            
        clean_text = text.replace("*", "").replace("#", "").strip()
        if not clean_text:
            continue
            
        file_counter += 1
        audio_file = f"temp_reply_{file_counter}.mp3"
        
        try:
            communicate = edge_tts.Communicate(clean_text, VOICE)
            loop.run_until_complete(communicate.save(audio_file))
            if not state.get("interrupted"):
                audio_queue.put(audio_file)
            else:
                if os.path.exists(audio_file):
                    try: os.remove(audio_file)
                    except: pass
        except Exception:
            pass

def audio_worker(audio_queue, state):
    """Watches for audio files and plays them sequentially to prevent overlap."""
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
    except Exception:
        pass
        
    while True:
        if state.get("interrupted"):
            break
        try:
            filepath = audio_queue.get(timeout=0.1)
        except queue.Empty:
            continue
            
        if filepath is None or state.get("interrupted"):
            if filepath and os.path.exists(filepath):
                try: os.remove(filepath)
                except: pass
            break
            
        try:
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if state.get("interrupted"):
                    pygame.mixer.music.stop()
                    break
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
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass

# ===================================================================

async def synthesize_and_play_single(text):
    """Fallback single-shot voice synthesis for basic greetings/goodbyes."""
    audio_file = "temp_single.mp3"
    try:
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(audio_file)
        
        pygame.mixer.init()
        pygame.mixer.music.load(audio_file)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
    except Exception:
        pass
    finally:
        try:
            if hasattr(pygame.mixer.music, 'unload'):
                pygame.mixer.music.unload()
            if os.path.exists(audio_file):
                os.remove(audio_file)
            pygame.mixer.quit()
        except:
            pass

def speak(text):
    """Wrapper to run single async TTS functionally."""
    asyncio.run(synthesize_and_play_single(text))

def listen(recognizer, mic):
    """Listen to microphone using PyAudio and Google STT."""
    try:
        with mic as source:
            print("\n" + "="*40)
            print("🎙️  [LISTENING...] Speak now!")
            audio = recognizer.listen(source, timeout=10, phrase_time_limit=10)
    except sr.WaitTimeoutError:
        return None
    except Exception as e:
        print(f"❌ Microphone read error: {e}")
        return None

    try:
        print("⏳  [PROCESSING...]")
        text = recognizer.recognize_google(audio)
        print(f"👤  [YOU SAID]: {text}")
        return text
    except sr.UnknownValueError:
        print("❌  [COULD NOT UNDERSTAND AUDIO]")
        return None
    except sr.RequestError:
        print(f"❌  [API ERROR]: Please check internet connection.")
        return None

def find_best_microphone():
    try:
        mics = sr.Microphone.list_microphone_names()
        for idx, name in enumerate(mics):
            name_lower = name.lower()
            if "airpods" in name_lower or "hands-free" in name_lower or ("headset" in name_lower and "realtek" not in name_lower):
                print(f"🎯 Auto-detected AirPods / Headset microphone at device [{idx}]: {name}")
                return idx
        prof_idx = loki.profile.get("mic_device_index")
        if prof_idx is not None and prof_idx < len(mics):
            return prof_idx
    except Exception:
        pass
    return None

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

def main():
    print(f"\n🧠 {loki.personality['name']} Voice Protocol Initialized.")
    print("="*40)
    
    os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
    
    r = sr.Recognizer()
    r.energy_threshold = 200
    r.dynamic_energy_threshold = False
    r.pause_threshold = 0.6
    
    mic_idx = find_best_microphone()
    try:
        try:
            mic = sr.Microphone(device_index=mic_idx)
            with mic as source:
                print("Adjusting microphone for ambient noise...")
                r.adjust_for_ambient_noise(source, duration=0.5)
            if r.energy_threshold > 300: r.energy_threshold = 200
        except Exception as e_mic:
            print(f"Configured mic_device_index {mic_idx} failed ({e_mic}). Falling back to default microphone...")
            mic = sr.Microphone(device_index=None)
            with mic as source:
                print("Adjusting default microphone for ambient noise...")
                r.adjust_for_ambient_noise(source, duration=0.5)
            r.energy_threshold = 200
    except Exception as e:
        print(f"❌ Microphone initialization failed: {e}")
        return
    
    greeting_text = f"Voice systems online. {loki.personality.get('greeting', '')}"
    print(f"🤖  LOKI: {greeting_text}")
    speak(greeting_text)

    last_ai_text = greeting_text

    while True:
        user_input = listen(r, mic)
        
        if user_input:
            if is_self_echo(user_input, last_ai_text):
                print(f"🔇 [SELF-ECHO DISCARDED]: {user_input}")
                continue
                
            lower_input = user_input.lower()
            if lower_input in ["exit", "quit", "goodbye", "shut down", "shutdown"]:
                farewell = "Shutting down the voice interface. Goodbye, sir."
                print(f"\n🤖  LOKI: {farewell}")
                speak(farewell)
                break
                
            # Define Queues & State for Streaming Pipeline
            text_queue = queue.Queue()
            audio_queue = queue.Queue()
            state = {"interrupted": False}
            
            # Start Background Workers
            t_tts = threading.Thread(target=tts_worker, args=(text_queue, audio_queue, state), daemon=True)
            t_audio = threading.Thread(target=audio_worker, args=(audio_queue, state), daemon=True)
            t_tts.start()
            t_audio.start()
            
            current_sentence = []
            all_tokens = []
            
            def on_token(token):
                if state.get("interrupted"): return
                print(token, end="", flush=True)
                current_sentence.append(token)
                all_tokens.append(token)
                
                # Check for end-of-sentence signs
                token_clean = token.strip()
                if token_clean and token_clean[-1] in ".!?":
                    sentence_str = "".join(current_sentence).strip()
                    if sentence_str and not state.get("interrupted"):
                        text_queue.put(sentence_str)
                    current_sentence.clear()
            
            # Forward input to Ollama and intercept streaming tokens
            loki.chat_with_LOKI(user_input, token_callback=on_token)
            
            last_ai_text = "".join(all_tokens).strip()

            if not state.get("interrupted"):
                if current_sentence:
                    sentence_str = "".join(current_sentence).strip()
                    if sentence_str: text_queue.put(sentence_str)
                text_queue.put(None)
                t_tts.join()
                t_audio.join()
            import time
            time.sleep(0.5)

if __name__ == "__main__":
    main()
