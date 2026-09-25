# Project Specification: F1 25 AI Driver Coach

## 1. Project Overview
**Goal:** Build a local Python application that reads live UDP telemetry from EA Sports F1 25, processes the raw data into actionable corner-by-corner performance metrics, and uses an LLM (Google Gemini via API) to provide automated, highly specific post-lap driving feedback via Text-to-Speech (TTS).

**Target Tech Stack:**
*   **Language:** Python 3.10+
*   **Data Ingestion:** standard `socket` and `struct` libraries.
*   **Data Processing:** `pandas` and `numpy` (for delta calculations).
*   **AI Integration:** `google-genai` (Gemini 2.5 Flash).
*   **Audio/TTS:** `edge-tts` (or local `piper` / `pyttsx3`) for low-latency voice delivery.

## 2. System Architecture
The application is separated into four distinct modular layers:

1.  **UDP Receiver (Thread 1):** Listens on port `20777` at 60Hz. Unpacks binary C-structs and pushes relevant frames into a thread-safe queue.
2.  **Telemetry Aggregator (Thread 2):** Consumes the queue. Maps telemetry to track position (`m_lapDistance`). Slices data into "Corners" based on braking zones and steering inputs. 
3.  **Delta Analyzer:** Compares the current lap's corner data against a Reference Lap (Personal Best). Extracts 3-4 key deltas (e.g., "Braked 15m early").
4.  **AI & Audio Engine:** Sends the structured text delta to the Gemini API at the end of the lap/sector. Streams the text response to the TTS engine.

## 3. Data Ingestion (F1 25 UDP Specs)
*   **Protocol:** UDP IPv4
*   **Port:** 20777
*   **Format:** Little-endian binary C-structs.
*   **Key Packets to Decode:**
    *   `PacketHeader` (Included in every packet, size 29 bytes). Extract `m_packetId`.
    *   `PacketId == 2` (Lap Data): Need `m_lapDistance`, `m_currentLapNum`, `m_sector`, `m_currentLapInvalid`.
    *   `PacketId == 6` (Car Telemetry): Need `m_speed`, `m_throttle`, `m_brake`, `m_steer`, `m_gear`.
    *   `PacketId == 13` (Motion Ex): Need `m_wheelSlipRatio` (rear wheel spin) and `m_wheelSlipAngle` (front understeer).

*Crucial Rule for the LLM writing the code:* Never index data by time. Always index data arrays by `m_lapDistance` to ensure Lap 1 and Lap 2 align spatially on the track.

## 4. Feature Engineering (The Delta Engine)
Do **not** send raw 60Hz telemetry to the AI. The Python code must reduce the corner into the following mathematical features before contacting the LLM:

*   **Braking Point ($D_{brake}$):** Track distance ($m$) where `m_brake` goes $> 0.2$ (20%).
*   **Apex Speed ($V_{min}$):** Minimum `m_speed` ($km/h$) during the cornering phase.
*   **Throttle Pick-up Point ($D_{throttle}$):** Track distance ($m$) where `m_throttle` goes $> 0.5$ (50%) after the apex.
*   **Max Slip / Instability:** Maximum rear `m_wheelSlipRatio` on corner exit.

**Example Delta Calculation for Python logic:**
`Delta_Brake_Point = Current_Lap_Brake_Point - Reference_Lap_Brake_Point`
*(Negative means braked earlier, positive means braked later).*

## 5. AI Integration & Prompting Strategy
**API Call:** Triggered when `m_currentLapNum` increments.
**Model:** Gemini 2.5 Flash (via `google-genai` SDK).
**Input format:** A tight, structured JSON or bulleted text string summarizing the 2 worst corners of the lap.

**System Prompt Design (For the AI Engine):**
> "You are an expert F1 race engineer. You will receive telemetry deltas comparing the driver's last lap to their personal best. 
> Respond with exactly two short, punchy sentences of advice meant to be read over the team radio. 
> Do not use pleasantries. Be direct. Example: 'You braked 10 meters too early into Turn 4, which compromised your apex speed. Carry more speed in and wait for the car to rotate before applying full throttle.'"

## 6. Development Phases (Instructions for Claude/LLM)

When executing this project, build it in the following phases. **Do not write the whole app at once.**

*   **Phase 1 - The UDP Sniffer:** Write a standalone Python script to bind to `0.0.0.0:20777`, parse the `PacketHeader`, and print out the `m_speed` and `m_brake` of the player's car from Packet ID 6.
*   **Phase 2 - Lap Distance Indexing:** Update the script to store telemetry in a Pandas DataFrame or custom class, indexed by `m_lapDistance`. Implement logic to detect when a lap finishes.
*   **Phase 3 - Corner Extraction:** Write an algorithm that detects braking zones (Brake > 0 -> Brake = 0) and records the entry distance, min speed, and exit distance.
*   **Phase 4 - API Integration:** Write a function using `google-genai` that takes a mock dictionary of corner deltas, applies the F1 engineer prompt, and returns the string response.
*   **Phase 5 - TTS & Multithreading:** Wrap the AI response in a text-to-speech function (e.g., `edge-tts`). Ensure the UDP listener runs on a background thread so packet ingestion doesn't block during network requests or TTS audio playback.