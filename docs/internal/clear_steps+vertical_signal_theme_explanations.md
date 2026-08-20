## Phase 0: The Foundation – Defining the Taxonomy (The **What**)

You must precisely define your "vocabulary." 
This is the heart of the project and will guide everything else.

Verticals, Use Cases, and Technologies: Start with the lists provided by Orange.
Create an initial whitelist of values ​​for each category.
* **Verticals**: Manufacturing, Retail, Finance, Public Sector, Healthcare, Defense, etc.
* **Use Cases**: Energy Optimization, Demand Forecasting, IT Operations Automation, Cybersecurity, Customer Experience, etc.
* **Technologies**: Computer Vision, Generative AI, IoT Platforms, Cloud Data Platforms, 5G, etc.

Why it is crucial: This taxonomy ==is the filter you will use to structure raw data==. A well-defined taxonomy makes the LLM's task (and yours) much easier and more precise.

---

## Phase 1: Signal Collection (The **Where**)

Gather external signals (news, reports, etc.). 
Focus on a limited number of high-quality sources.

#### Tools and APIs (MVP):
* **NewsAPI**: A simple, free (with limits) API for aggregating news from around the world. You can search using keywords like _manufacturing AI_, _retail computer vision_, etc.
* **RSS Feeds**: An even simpler, cost-free approach. Find RSS feeds from outlets like ComputerWeekly.com or MobileWorldLive.com, or from the blogs of tech companies and startups. You can use Python libraries like `feedparser` to read them.
* **Google News RSS**: You can create search queries on Google News and generate an RSS feed of the results.

Practical approach for the MVP: ==Create a Python script that queries your sources (API or RSS) once a day (or on demand) using a predefined list of keywords. Save the results== (title, date, link, excerpt) ==in a structured format== (e.g., a JSON file or an SQLite database). This constitutes your **"raw data"** (raw signals).

---

## Phase 2: Extraction and Creation of OSs (The **How**)

This is where AI comes into play. You need to transform raw signals into structured Opportunity Spaces (OSs).

#### Tools and APIs:
* **LLM (Large Language Model) via API**: Use a model like `gpt-3.5-turbo` or `gpt-4o` (OpenAI), or an open-source alternative (e.g., via Hugging Face or Ollama) if you have restrictions. An LLM is perfect for:
	-  _Summarizing_ : Taking an article and producing a 2–3 sentence summary.
	*  _Extracting Themes_ : Identifying emerging themes and innovation phrases.
	*  _Mapping to Taxonomy_ : Given a summary, asking the LLM to classify it by Vertical x Use Case x Technology.

#### How to build the logic (Prompt Engineering):
Your main task will be writing a good "prompt." 
Here is an example of a prompt to send to the API for each signal:

```text
You are an analyst for Orange Business. Analyze the following market signal and:

1. Summarize it in one sentence.
2. Identify the main theme.
3. Classify it according to this taxonomy. **Choose only from the values ​​listed below.**

**Verticals (choose ONE):**
Manufacturing, Retail, Finance, Public Sector, Healthcare, Defense, Automotive, Fast Moving Consumer Goods, Industry, IT and Services

**Use Case (choose ONE):**
Energy Optimization, Demand Forecasting, IT Operations Automation, Imaging Analytics, Network Modernization & SD-WAN, Cloud Infrastructure Modernization, Cyber ​​Defence & Zero Trust, Customer Experience, Employee Experience, Operational Excellence, Digital Infrastructure, Data Sovereignty, Cybersecurity

**Technologies (choose ONE):**
Cloud Data Platform, IoT Platforms, Computer Vision, Machine Learning, Generative AI, Network & SD-WAN, Cloud, Cybersecurity, 5G, IoT, AI

**Signal to analyze:**
[Insert article title and excerpt here]
```

The ==LLM's output will be a candidate OS==.

---

## Phase 3: Curation and Cleaning (The **What to Exclude**)

Not all generated OSs will be valid. You need to clean the data.

#### Cleaning Logic:
*  _Remove generic items_ : Automatically discard any OSs that contain only generic themes such as _AI,_, _Cloud_, or _Cybersecurity_.
*  _Merge similar themes_ : If two OSs are virtually identical (e.g., Retail x Demand Forecasting x Machine Learning and Retail x Demand Forecasting x Generative AI), you can merge them or keep just one. This task can be performed manually during the MVP phase or automated using another LLM prompt.

This phase transforms "candidate" OSs into "curated" OSs that are ==ready for the radar==.

---

## Phase 4: The Scoring System (The **Why**)

The **scoring must be transparent and explainable**. It must not be a "black box."

#### Scoring Logic 
##### for MVP:
Create a composite score based on the criteria provided by Orange. 

For the MVP, you can simplify:
- _Market Signal Strength (30%)_ : **How many mentions** has the topic received? The more sources citing it, the higher the score.
- _Source Diversity (20%)_ : **How many different sources** (e.g., different news outlets) are discussing it?
- _Evidence Quality (20%)_ : You can assign **greater weight to sources you consider more authoritative** (e.g., reuters.com vs. an obscure blog).
- _Orange Business Strategic Relevance (30%)_ : **How relevant is it** to Orange Business domains?

#### Practical calculation:
* For the first three points, you can use ==proxies==. For example, Market Signal Strength could be the total number of signals collected for that OS.
* For point 4, you could ==create a mapping==: if the OS falls within a key domain like Cybersecurity or Healthcare, it receives a higher score.

The final result is a number (e.g., from 0 to 100). However, the important thing is that **each OS must include an "explanation" field** stating, for instance: "High score (85/100) because it was cited in 5 articles from 3 different sources—2 of which are high-profile (Reuters, WSJ)—and the topic aligns with our Cloud strategy."

##### after we have an MVP: _How to calculate each factor in practice_
Here is how you can calculate each factor using real data:

1. **Market Signal Strength**
	* How to calculate it: Count the total number of signals (articles, reports, etc.) mentioning that OS.
	* Example: If an OS is cited in 10 articles, it will have a higher score than one cited in 3 articles.
	* Normalization: Divide by the maximum number of mentions across all OSs and multiply by 100.
2. **Source Diversity**
	* How to calculate it: Count the number of unique sources (e.g., Reuters, Bloomberg, TechCrunch) mentioning that OS.
	* Example: If an OS is cited by 5 different sources, it will have a higher score than one cited by only 1 source (even if it has many mentions from that same source).
	* Normalization: Divide by the maximum number of unique sources across all OSs and multiply by 100.
3. **Evidence Quality** 
	* How to calculate it: Assign an "authority weight" to each source (e.g., Reuters=10, unknown blog=1).
	* Example: An OS cited by Reuters and the WSJ will have a higher score than one cited only by minor blogs.
	* Normalization: Sum the source weights for that OS, divide by the maximum value, and multiply by 100.
4. **Orange Business Strategic Relevance**
	* How to calculate it: Create a mapping that assigns a score to each combination of Vertical, Use Case, and Technology based on its relevance to Orange.
	* Example: If an OS operates in Healthcare (a strategic area) and utilizes Cybersecurity (a key Orange competency), it will receive a high score.
	* Normalization: Assign a score from 0 to 100 for each combination.
5. add to the equation **Novelty & Momentum**
> "Novelty and momentum: Measures whether the topic is emerging, rising, or changing."

* **Novelty**: How new/emerging is the topic? Has it just appeared, or is it already saturated?
* **Momentum**: Is the topic accelerating (more signals over time) or dying out (fewer signals)?
Calculating novelty and momentum ==requires historical data== (signals collected over time). That is why Orange considers it a "nice-to-have" rather than an MVP requirement.

##### 5.1 How you can implement it in the next phase:

1. **Data preparation**
You need:
* A collection of signals with timestamps (publication dates).
* A categorization of each signal into an OS (Vertical x Use Case x Technology).

1. **Novelty Calculation**
Novelty measures how "new" and not yet saturated a topic is. 
The more recent the signals, the higher the score.
> Calculate the average age of the signals for a given OS.

Example:
```text
OS A: signals from 1, 3, and 5 days ago → average age = 3 days → score = ~99
OS B: signals from 100, 150, and 200 days ago → average age = 150 days → score = ~59
```

3. **Momentum Calculation**
Momentum measures whether the theme is accelerating or slowing down. 
The more signals received in recent weeks, the higher the momentum.
> Compare the number of signals across two time windows.

4. **Integration into the total score**
Once Novelty and Momentum have been calculated, you can integrate them into the scoring formula (the same presented by orange, sum of percentages).

5. **Combined Novelty & Momentum calculation**
For a simpler calculation, you can combine the two factors into one.

6. **Dashboard Visualization**
Once "Novelty and Momentum" have been implemented, you can visualize them on the dashboard in several ways:
* Option 1: Bubble Size
	* Use bubble size to represent "Momentum." -> Larger bubbles = rapidly accelerating theme.

* Option 2: Bubble Color
	* Use color to represent "Novelty." -> Blue = mature theme; Red = emerging/new theme.

* Option 3: "Trend" Filter
	* Add a filter to view only themes with positive (rising) or negative (falling) momentum.

* Option 4: "Time Horizon" Label
Based on Novelty and Momentum, classify themes as "Now" (mature, stable momentum), "Next" (emerging, rising momentum), or "Later" (new, low momentum).

##### 5.2 Challenges and Solutions:
* Insufficient data: For new themes (few signals), novelty and momentum calculations are unstable. Use a default score (e.g., 50) until you have at least 5 signals.
* Bias toward themes with many signals: A theme with 100 signals may appear to have higher momentum than one with 5 signals. Normalize based on total volume.
* Periodicity: Not all signals have the same frequency. Some sources (e.g., annual reports) publish less frequently than others (e.g., daily news). Take this into account.
* Seasonality: Some themes may be seasonal (e.g., annual conferences). Consider longer time windows (e.g., 90 days).

##### 5.3 example of implementation

```python
import pandas as pd
from datetime import datetime, timedelta

class NoveltyMomentumCalculator:
    def __init__(self, current_date=None, window_days=30):
        self.current_date = current_date or datetime.now()
        self.window_days = window_days
    
    def calculate(self, signal_dates):
        """Calculates the combined novelty and momentum score."""
        if not signal_dates:
            return 0
        
        # Convert to datetime if necessary.
        dates = [pd.to_datetime(d) for d in signal_dates]
        
        # Novelty
        ages = [(self.current_date - d).days for d in dates]
        avg_age = sum(ages) / len(ages)
        novelty = max(0, 100 - (avg_age / 365 * 100))
        
        # Momentum
        recent_cutoff = self.current_date - timedelta(days=self.window_days)
        old_cutoff = self.current_date - timedelta(days=self.window_days*2)
        
        recent = len([d for d in dates if d >= recent_cutoff])
        old = len([d for d in dates if old_cutoff <= d < recent_cutoff])
        
        if old == 0:
            momentum = 100 if recent > 0 else 0
        else:
            momentum_raw = (recent - old) / (recent + old)
            momentum = (momentum_raw + 1) * 50
        
        # Combined scoring
        return (novelty * 0.4) + (momentum * 0.6)

# Usage
calculator = NoveltyMomentumCalculator(window_days=30)
score = calculator.calculate(["2026-08-01", "2026-08-05", "2026-08-10"])
print(f"Novelty & Momentum Score: {score:.1f}")
```

---

## Phase 5: The Radar and the Dashboard (The **Where to View It**)

The final product must be a visual dashboard.

#### Tools:
**Streamlit** or **Dash (Plotly)**: These are Python frameworks perfect for creating data science dashboards in just a few hours. They are ideal for an MVP.

#### What it must show (MVP):
* _Bubble Chart_ : A classic "innovation radar", where each bubble represents an OS. For example, ***Attractiveness** on the X-axis* and ***Urgency** on the Y-axis*. ***Bubble size*** can *represent* *Market Potential*. 
* _Filters_ : Implement *filters for **Vertical** and **Domain*** (Smart Industries, Cybersecurity, etc.). This is essential for "actionability".
* _OS Details_ : Clicking on a bubble should display a card containing:
		-  The **OS name** (Vertical x Use Case x Technology).
		-  The **Attractiveness score** and its **explanation**.
		-  **Sources** (links to articles).
		-  The "**Why it's hot now**".
		-  A **recommended "Next step"** (e.g., "Explore further with a client in the Finance sector," "Prepare a brief for the sales team").

---

## Practical Role Assignment

Based on the suggested roles, here is how you could divide the work over the coming days:
* **Data Architect (Siegried)**: Focuses on Phases 1, 2, and 4. Builds the data pipeline: scripts to call APIs/RSS feeds, interact with the LLM, and the scoring system.
* **Git Manager / Frontend (Hiba)**: Focuses on Phase 5. Starts building the dashboard structure using Streamlit right away—even with dummy data—to create a visual "container" for the real data.
* **Documentation Specialist (Gaetan)**: Works on Phases 0 and 3. Refines the taxonomy, defines whitelists, and—together with the Data Architect—defines the rules for data cleaning and the removal of generic topics.
* **Team Leader (Irene)**: Coordinates the entire effort, ensures integrations work, and guarantees the MVP is delivered on time.

> [! IRENE'S NOTES HERE:]
> I kept this paragraph because I think gives valuable suggestions on division of responsibilities among teammates (especially in Siegried and Gatean cases), but i don't like mine: here it feels like I only have to control everyone instead of having also a specific responsibility of my own in the whole project as well.

---

## Tips for the MVP

* Start with dummy (or "sample") data: **don't wait for the perfect data pipeline to start building the dashboard**. Create 10–15 sample OS entries—complete with scores and explanations—to test the interface and filters.

* Use a simple database: SQLite is perfect. A **single table containing all the necessary columns** (OS Name, Vertical, Use Case, Tech, Score, Explanation, Sources, Date, etc.) will suffice.

* Automate the refresh process: The **pipeline** (Phases 1–4) should be a script you can **run to update the radar**. This is a **key requirement**.


> [!IMPORTANT] 
> **Document everything**: Especially **design decisions** (such as why you chose a specific scoring weight) and the **prompts used for the LLM**. This documentation will be invaluable for the final presentation. 
> _(**Irene here**: this is actually what [Obsidian](https://obsidian.md/) is really helping with and why I suggested it yesterday)_

---

## Expressions Explanations

### Vertical
In the context of the Orange Innovation Radar project, a **"vertical"** refers to a specific **customer industry or market sector**.

It is a foundational element of the challenge because it represents the "who" in the innovation equation. Here is how it functions within your project:

1. The Core Component of an Opportunity Space (OS)

The primary goal of your tool is to identify **Opportunity Spaces**, which are defined by the intersection of three specific elements: **Vertical x Use Case x Technology**. For example, an OS might be _Manufacturing_ (Vertical) x _Energy Optimization_ (Use Case) x _Computer Vision_ (Technology).

2. Strategic Filtering and Targeting

Verticals are used as a primary **filtering dimension** in the radar dashboard. This allows different team members to find relevant insights quickly:

- **Sales Teams:** Can filter for a specific vertical (like Banking) to find 1–2 tailored innovation topics to discuss with a customer.
- **Strategists:** Can identify which industry sectors have the most "hot" or urgent opportunities.

3. List of Orange Business Verticals

The sources specifically list the industry sectors that the radar tool must consider. These include:

- **Manufacturing:** Including heavy industry, consumer goods (FMCG), and materials.
- **Finance:** Including banking and insurance services.
- **Public Sector:** Including government and defense.
- **Healthcare and Lifesciences:** These are noted as sectors where "trust matters most".
- **Others:** Retail, Automotive, Energy, Construction, and Media & Entertainment.

In short, when the team says "vertical," they mean the **industrial context** where a specific technology will be applied to solve a business problem. Every innovation topic your team extracts must map to one of these industry worlds.

### Signal
A Signal is a **piece of raw, specific, and time-stamped information originating from an external source**. It is an event, an announcement, a data point, or a concrete observation **indicating that something is changing in the market, technology, or regulatory landscape**.

Characteristics of a Signal:
* _It is raw_  : It has not yet been interpreted or processed.
* _It is specific_ : It refers to a precise event or data point.
* _It is time-stamped_ : It is anchored in time (e.g., "On May 15, 2026, Microsoft announced X").
* _It has a source_ : It can be attributed to a clear origin (e.g., a Reuters article, a press release, a Gartner report).
* _It represents the "what"_ : It answers the question, "What happened?"

Concrete examples of Signals (from your documents):
* "A new EU GDPR regulation regarding AI has been approved." (Regulation Update)
* "Amazon has launched a new computer vision service for warehouse inventory management." (Technology Announcement)
* "A McKinsey report estimates that the AI-optimized energy market will grow by 25% annually." (Market Move / Analyst Report)
* "A German manufacturing company reduced energy consumption by 15% using IoT." (Proof Signal / Case Study)

In your workflow, Signals **serve as the process input**. They are the information **you collect via APIs and RSS feeds**.

### Theme
A Theme is a **generalization, pattern, or emerging issue derived from the analysis of multiple Signals**.

Characteristics of a Theme:
* _It is synthesized_ : It is the result of interpreting signals.
* _It is abstract and recurring_ : It is not a single event, but a concept that emerges from multiple sources.
* _It lacks a specific date_ : It is a trend or area of ​​interest that is currently developing.
* _It represents the "why" or "what is happening"_ : It answers the question, "What pattern do we see?"

Concrete examples of Themes (from your documents):
* "Growing interest in energy optimization within the manufacturing industry." (Emerges from signals such as market reports, startup announcements, and success stories)
* "Computer vision is becoming a key technology for inventory management in retail." (Emerges from Amazon announcements, startup articles, and analyst reports)
* "Public sector organizations are accelerating the adoption of Zero Trust cybersecurity solutions." (Emerges from regulations, vendor announcements, and tenders)
* "Generative AI is transforming the customer experience in financial services." (Emerges from numerous bank announcements, industry reports, and articles)

In your workflow, **Themes** are the output derived from Signals. They **act as the bridge between raw data and Opportunity Spaces**.


### How do Signals and Themes fit into practical workflow
In practice, the script (leveraging the LLM) should work like this:
1. **Gathering Signals**: Your script takes an article (e.g., "Siemens launches a new IoT sensor for energy monitoring in factories") and passes it to the LLM.
2. **Prompt asks the LLM to** do two things:
	* **Summarize the Signal**: "Summarize this market signal in one sentence." (Output: "Siemens has launched an IoT sensor for energy monitoring.")
	* **Extract the Theme**: "Identify the main theme emerging from this signal." (Output: "The adoption of IoT for energy efficiency in industrial manufacturing is accelerating.")
3. **Creating the OS**: After analyzing many similar signals regarding IoT and energy efficiency, your system (or another LLM prompt) can consolidate these themes into a single Opportunity Space:
	* _Vertical_ : Manufacturing
	* _Use Case_ : Energy Optimization
	* _Technology_ : IoT Platforms.

> [!In short:]
>  Signals are the raw "bricks." Themes are the "patterns" you recognize by looking at the bricks. OSs are the "houses" you build using those patterns, following Orange's taxonomy.

