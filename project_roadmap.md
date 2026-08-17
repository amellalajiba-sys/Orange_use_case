# Project Roadmap

To execute the **Orange Innovation Radar** challenge professionally within a two-week timeframe, your team must focus on building a tool that identifies and scores **Opportunity Spaces (OS)**—defined as the intersection of a **Vertical**, a **Use Case**, and a **Technology**.

Here is a strategic guide for your project based on the requirements from the Orange Innovation team:

### 1. The OS Discovery Process (Workflow)

Your project should follow a structured five-step process to transform raw data into a functional radar:

- **Signal Collection:** Gather external signals such as news, analyst reports, regulatory updates, and market moves.
- **Theme Extraction:** Identify emerging problems and repeated innovation phrases from these signals.
- **OS Creation:** Structure candidate opportunities into the **Vertical x Use Case x Technology** format (e.g., _Manufacturing x Energy Optimization x Computer Vision_).
- **Curation:** Clean the data by removing generic themes (like "AI" or "Cloud") and merging similar topics to ensure the radar is actionable for sales teams.
- **Scoring:** Rank topics based on attractiveness, urgency, and Orange’s "right to win".

### 2. Practical Insight Extraction (APIs and AI)

The sources suggest that **extracting insights can be automated with AI**.

- **Searching for signals:** The process begins by searching keywords on the internet for news and market moves.
- **Using APIs:** While the sources do not name specific third-party APIs, your **Data Architect** should seek out APIs that aggregate business news, regulatory databases, or analyst insights (e.g., News APIs or RSS feeds).
- **AI Integration:** AI is specifically recommended for **managing collected data** and **identifying repeated themes**. You can use Large Language Models (LLMs) via API to summarize signals and map them to the required "Vertical x Use Case x Technology" taxonomy.

### 3. Professional Standards and "Actionability"

To be professional and useful to Orange, the tool must prioritize **actionability** over mere summary.

- **Trust and Transparency:** Every score must be explained, not just presented as a number. Users must be able to see the **source evidence** and **signal type** (e.g., regulation vs. market trend).
- **Persona Filtering:** The radar must allow users to filter by **Vertical** (e.g., Finance, Healthcare), **Geography**, and **Persona** (e.g., CIO, CISO, COO).
- **The "Next Step":** Every innovation topic should include a "recommended next action," such as a conversation hook for a customer meeting.

### 4. Team Role Alignment

- **Team Leader:** Ensure the project meets the **Minimum Viable Product (MVP)** requirements first: defining OS, building the refreshable discovery process, and creating the visual dashboard.
- **Data Architect:** Focus on the **scoring calculation** (e.g., balancing market signal strength, source diversity, and evidence quality) and the technical pipeline for "cleaning" raw signals into structured OS.
- **Documentation Specialist:** Map every topic to **Orange's business domains** (Smart Industries, Cybersecurity, etc.) to ensure strategic relevance.
- **Git Manager:** Manage the codebase for the **visual radar dashboard**, ensuring that version control supports the "living" nature of the radar as topics rise and fade.

### 5. Managing the Timeframe (MVP vs. Nice-to-Haves)

Given the two-week limit, prioritize the **MVP**:

1. **Define the OS** taxonomy.
2. **Build the scoring system** for attractiveness.
3. **Generate the visual dashboard.**