import os
import sys
import json
import time
import speech_recognition as sr

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_FILE = os.path.join(BASE_DIR, "memory", "profile.json")

def load_profile():
    if os.path.exists(PROFILE_FILE):
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_profile(profile):
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)

def test_microphone(index, name):
    print(f"\nTesting: [{index}] {name}")
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    try:
        mic = sr.Microphone(device_index=index)
        with mic as source:
            print("Listening for 2 seconds... Please make some noise or speak!")
            audio = recognizer.record(source, duration=2.0)
            
        raw_data = audio.get_raw_data()
        if not raw_data:
            print("❌ No audio data captured.")
            return 0
            
        import math
        import struct
        count = len(raw_data) / 2
        format_str = f"<{int(count)}h"
        try:
            shorts = struct.unpack(format_str, raw_data)
        except Exception:
            shorts = []
            
        sum_squares = sum(s * s for s in shorts)
        if count > 0:
            rms = math.sqrt(sum_squares / count)
        else:
            rms = 0
            
        print(f"✅ Capture finished. Measured Sound Level (RMS): {rms:.1f}")
        return rms
    except Exception as e:
        print(f"❌ Error testing this device: {e}")
        return -1

def main():
    print("==================================================")
    print("       L.O.K.I Microphone Diagnostic Utility      ")
    print("==================================================")
    
    mics = sr.Microphone.list_microphone_names()
    if not mics:
        print("No audio input devices found. Please plug in a microphone.")
        return
        
    print("\nAvailable Input Devices:")
    for idx, name in enumerate(mics):
        print(f"  [{idx}] {name}")
        
    profile = load_profile()
    current_mic = profile.get("mic_device_index", None)
    print(f"\nCurrently configured mic_device_index in profile.json: {current_mic}")
    
    print("\n--- AUTO-DETECTION MODE ---")
    print("We will test all inputs. Please talk or make noise continuously during the test.")
    input("Press Enter to start testing all microphones...")
    
    results = []
    for idx, name in enumerate(mics):
        name_lower = name.lower()
        if "output" in name_lower or "speaker" in name_lower or "sound driver" in name_lower or "line out" in name_lower:
            continue
            
        rms = test_microphone(idx, name)
        if rms > 10:
            results.append((idx, name, rms))
            
    print("\n==================================================")
    print("                   TEST RESULTS                   ")
    print("==================================================")
    if not results:
        print("No microphone detected any active sound levels. Make sure your microphone is not muted in Windows settings.")
    else:
        results.sort(key=lambda x: x[2], reverse=True)
        print("Microphones ranked by detected sound level:")
        for idx, name, rms in results:
            print(f"  [{idx}] {name} (Volume: {rms:.1f})")
            
        best_idx, best_name, _ = results[0]
        print(f"\nRecommended Device: [{best_idx}] {best_name}")
        
        choice = input(f"\nDo you want to save device index {best_idx} to your profile? (y/n): ").strip().lower()
        if choice == 'y':
            profile["mic_device_index"] = best_idx
            save_profile(profile)
            print(f"Saved mic_device_index = {best_idx} to profile.json.")
            return

    manual = input("\nEnter a device index to set manually (or press Enter to exit): ").strip()
    if manual.isdigit():
        idx = int(manual)
        if 0 <= idx < len(mics):
            profile["mic_device_index"] = idx
            save_profile(profile)
            print(f"Saved mic_device_index = {idx} to profile.json.")
        else:
            print("Invalid device index.")

if __name__ == "__main__":
    main()
