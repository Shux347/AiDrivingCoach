# Future Roadmap: Historical Data & Driver Progression

## 1. The Goal

Currently, the F1 25 AI Coach operates on a per-session basis, comparing live telemetry to a session-specific Personal Best. The next evolutionary step is to implement **Long-Term Persistence**. By storing aggregated results, telemetry summaries, and historical optimal laps across multiple races and sessions, the AI can track driver progression, identify fundamental driving habits, and act as a season-long race engineer.

## 2. The Core Challenge: Data Volume & Context

F1 25 telemetry generates massive amounts of data at 60Hz. Saving raw UDP dumps for every race will quickly consume gigabytes of storage and become impossible to query efficiently. Furthermore, a PB on soft tyres in qualifying cannot be directly compared to a race stint on worn hard tyres in the rain.

To solve this, the system must transition from flat files to a structured database and implement **Contextual Indexing**.

## 3. Implementation Phases

### Phase 1: Local Database Migration (SQLite / DuckDB)

Replace the temporary JSON/CSV session files with a lightweight, embedded database.

* **Technology:** SQLite (built into Python) or DuckDB (optimized for analytical queries on Pandas DataFrames).
* **Storage Strategy:** Do *not* store raw 60Hz data long-term. Instead, store:
  * Session Metadata (Track ID, Weather, Session Type).
  * Lap Summaries (Lap times, sector times, tyre compound, fuel load, wear levels).
  * Corner Aggregates (The 4-feature delta engine outputs: $D_{brake}$, $V_{min}$, $D_{throttle}$, Max Slip).
  * The single "Theoretical Optimal Lap" (from the previous roadmap) for each track/condition combo.

### Phase 2: Contextual Indexing & Filtering

Data must be tagged with game state variables so comparisons remain physically relevant.

* **Required Tags from UDP (`SessionPacket` & `CarStatusPacket`):**
  * `m_trackId`: (e.g., Monza vs. Silverstone).
  * `m_weather`: (Dry, Light Rain, Heavy Rain).
  * `m_tyreCompound`: (Soft, Medium, Hard, Inter, Wet).
  * `m_tyreWear`: (Comparing a fresh tyre lap vs. 50% wear).
* **Query Logic:** When starting a new race, the Python engine queries the database for the PB/Optimal lap matching the *current* track and weather, dynamically loading the correct reference file.

### Phase 3: Trend Analysis (The Habit Engine)

Write analytical scripts to identify persistent driving traits across *different* tracks.

* **Cross-Track Metrics:** Group corners by type (e.g., Low-Speed Hairpin, High-Speed Sweeper).
* **Detection Logic:** If the delta engine shows a driver consistently has high `m_wheelSlipRatio` on the exit of low-speed corners at Bahrain, Monaco, and Singapore, the system flags a foundational habit: "Aggressive throttle application in traction zones."

### Phase 4: Retrieval-Augmented Generation (RAG) for the AI Coach

Upgrade the Gemini AI integration to use long-term memory.

* **Pre-Session Briefing:** Before the car leaves the garage, the app queries the database for historical performance at this track and feeds it to the LLM.
  * *Example Output:* "Welcome back to Spa. Last time here, you struggled with understeer through Pouhon and consistently braked too late into the Bus Stop chicane. Let's focus on smooth trail-braking today."
* **Persistent Prompting:** Inject the driver's "Habit Engine" traits into the Gemini system prompt so the AI personalizes its live advice based on known weaknesses.

## 4. Next Steps for the Codebase

1. Create a `database.py` module to handle SQLite connections and table schemas (`sessions`, `laps`, `corner_metrics`).
2. Update `app.py` to write summary data to the database upon lap completion or session end.
3. Design a simple local dashboard (e.g., using Streamlit or Gradio) to visualize historical progression, lap time trends, and corner-by-corner improvement over weeks or months.