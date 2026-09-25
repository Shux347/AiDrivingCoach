# Future Roadmap: Theoretical Optimal Lap (Ideal Lap)

## 1. The Goal
Currently, the F1 25 AI Coach compares live telemetry against a single, continuous Personal Best (PB) lap. The next major evolution is to implement a **Theoretical Optimal Lap** (often called an Ideal Lap in MoTeC or professional motorsport engineering). This will allow the AI to coach the driver toward their absolute physical limit based on their own best individual corners.

## 2. The Core Challenge: The Physics Trap
We cannot simply take the fastest Turn 1 and stitch it to the fastest Turn 2 from a different lap. If a driver brakes absurdly late for Turn 1, they will set a record micro-sector time, but park the car on the apex and ruin their exit speed. Stitching this to a Turn 2 entry would create a physically impossible trajectory. 

To solve this, the next iteration must introduce **Boundary Conditions**.

## 3. Implementation Phases

### Phase 1: Macro-Sector Ideal (The Stepping Stone)
Before slicing individual corners, upgrade the state manager to track the game's default 3 sectors independently.
* **Logic:** Sum the best Sector 1, 2, and 3 times across all laps in a session. 
* **Why it works easily:** Sector lines almost always occur on straights. Track position and exit trajectories rarely conflict across these boundaries, making simple addition mathematically safe.

### Phase 2: Micro-Sector Slicing
Transition the `m_lapDistance` indexer to break the track into smaller, corner-to-corner segments.
* **Definition:** A micro-sector begins at the start of a braking zone and ends at the start of the *next* braking zone.
* **Data Structure:** Instead of storing one continuous `LapData` array, the system will maintain a list or dictionary of `MicroSector` objects.

### Phase 3: The Boundary Condition Engine (Crucial)
When a live micro-sector time beats the stored optimal micro-sector time, the ingestion engine must run two physics checks before overwriting the file:
1. **The Exit-Velocity Check:** The car's speed (`m_speed`) at the exact end of the new micro-sector must be $\ge$ the exit speed of the previously stored optimal sector.
2. **The Lateral Position Check (Optional but recommended):** The car's lateral distance from the racing line/center (derived from `MotionPacket` coordinates) at the exit must be within a predefined tolerance (e.g., $\pm 2$ meters) of the previous optimal line.

*If the new micro-sector is faster but fails these checks, it is discarded as a "compromised exit" and is not added to the Theoretical Optimal Lap.*

### Phase 4: Composite In-Memory Lap ("Frankenstein Lap")
Update the storage mechanism to splice passing micro-sectors together.
* The reference lap sent to the AI is no longer a single real lap. It is a dynamically generated, continuous array constructed from perfectly matched micro-sectors.
* The system will need a smoothing function (e.g., linear interpolation) at the splice points (the straights) to prevent data jitter from confusing the delta engine.

## 4. Enhanced AI Prompting
Once Phase 3 is active, update the Gemini 2.5 Flash system prompt to leverage the new data context. 
* **New Capability:** The AI can now tell the driver what is *possible*, not just what they did last time.
* **Prompt Example:** *"Your exit out of Turn 4 was 2 tenths slower than your theoretical optimal. Telemetry shows you can carry 120 km/h through the apex if you replicate your trail-braking from lap 12. Focus on matching that entry."*