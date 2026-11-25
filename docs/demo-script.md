# Utilities Management Agent: demo script

**Do** is what you click. **Say** is what you speak. `[name]` is whoever the screen shows: it changes with the shift.
Length: about 10 minutes.

## Before you start (not shown to the client)

| # | Do |
|---|---|
| 1 | Open the app in a wide or full-screen browser window and sign in. |
| 2 | Menu > **Setup and information** > **Data connectors** > open **Mock data for the proof of concept** > click **Re-create mock data (about 20 s)**. This brings back the open gas issue. |
| 3 | Click **Issues**. Check that you see 6 open issues and 1 critical one. Wait a minute if the app has just started. |

The **Reset demo** button on the plant map does not reopen a closed issue. Use step 2.

## 1. Opening

| Do | Say |
|---|---|
| Stay on **Issues**. | "Every plant knows this moment. Something goes wrong on the utilities side, and the questions start. What is wrong? Where? Who has to go? How long has it been? Was it really fixed? This agent answers all of that in one place." |
| | "What you will see is a proof of concept running on simulated data." |

## 2. Architecture (say this before you click anything)

```
Plant readings  -->  Monitoring engine  -->  Issue + owner  -->  Web screens
(simulated today)    (checks every second)   (database)          (list, 3D map, overview)

Your systems    -->  Data connectors    -->  Database      <--  Ask the agent (AI chat)
(SQL, REST, CSV)     (read only)             (history)          reads, advises, never operates
```

| Do | Say |
|---|---|
| Show the diagram above on a slide, or open **Setup and information** > **How it works** (it plays by itself; click a step to stay on it). | "There are five parts. Let me walk through them in order." |
| Point at **Plant readings**. | "First, readings. Today a built-in simulator produces them for seven utilities: compressed air, steam, chilled water, cooling tower, HVAC, water and gas." |
| Point at **Monitoring engine**. | "Second, the monitoring engine. Every second it compares readings with engineering limits and known fault patterns. These are clear rules, so the same reading always gives the same result. It is not a language model guessing." |
| Point at **Issue + owner**. | "Third, when something stays abnormal, it raises one issue, writes the probable cause from the readings, and picks the person: right team, on shift now, covering that zone. If nobody acknowledges in time, it escalates." |
| Point at **Web screens**. | "Fourth, the screens. They all read the same facts, so the list, the map and the overview always agree." |
| Point at **Ask the agent**. | "Fifth, the AI chat. It answers questions in plain language using the same data. It can only read and advise. It cannot change an issue or operate equipment." |
| Point at **Data connectors**. | "Your own systems connect here, read only. Today that data lands in the database for history and analysis. Feeding your live sensors into the monitoring engine is the next step." |

## 3. The issue (the ticket)

| Do | Say |
|---|---|
| On **Issues**, point at the number tiles. | "At the start of a shift the team sees how many issues are open, how many need attention, and how many nobody has picked up." |
| Click the **red critical row** (combustible gas). | "Here is a critical one. Gas reading above its limit." |
| Point at **What happened** on the right. | "What is wrong: the actual reading next to what is expected." |
| Point at **Where and who**. | "Where: the Gas Station, at the gas regulating skid. Who: [name], safety officer, with the extension." |
| Point at the **timer** on the row. | "How long: a live timer against a 2 minute target to acknowledge." |
| Point at **What to do** and **Timeline**. | "What to do, and every step so far with its time. Nothing gets lost in a phone call." |

## 4. Live response on the 3D map

| Do | Say |
|---|---|
| Click **Show on plant map**. | "Now the same issue on the plant itself. The equipment is pulsing red." |
| Point at the **Live response** strip. | "These five steps are the life of an issue: detect, notify, go, fix, verify." |
| Point at the name tag by the **Control room**. | "The agent has already notified [name]. It is waiting for them to take it." |
| Click **Acknowledge** in the strip. | "I acknowledge it. Now it has an owner, and you can see [name] heading to the equipment." |
| Wait while the figure walks (about 8 seconds). | "This figure shows the stage of the response. It is a visualisation, not live location tracking." |
| When they arrive, point at the **blue ring**. | "They are on site and working. Notice the gas reading on the right is still high, because nothing is fixed yet." |
| Type `Regulator replaced and joints leak tested`, then click **Record the fix**. | "I record what was done. This goes into the history, so next time we know what worked." |
| Point at the **green scan** and the reading falling. Wait about 15 seconds. | "Now the important part. Nobody can simply press done. The agent checks the fresh readings." |
| Click **Verify with telemetry**. If it refuses, wait a few seconds and click again. | "The readings are back inside the limits, so the issue closes. If they were not, it would refuse and say why." |
| Point at the **top bar**, the **menu badge** and the **Gas** entry in Systems. | "Watch what changed without refreshing: one alert fewer, the badge dropped, gas is green. One fact, shown the same everywhere." |
| Let the figure walk back. | "Closed, and [name] is heading back." |

## 5. Plant overview

| Do | Say |
|---|---|
| Click **Plant overview**. | "This is the manager's view: one tile per utility with its status." |
| Point at the **Gas** tile. | "Gas now reads all normal, because we just closed it." |
| Click another tile with an open issue. | "Usage today against yesterday and against the normal range, and the reading behind the problem. The usage figures here are modelled demo data." |
| Click **Last 7 days**, then point at **Needs attention**. | "The week at a glance, and what to deal with next." |

## 6. Ask the agent

| Do | Say |
|---|---|
| Click **Ask the agent**. | "If you would rather ask than click, just ask." |
| Click the suggestion **What needs attention first right now...** | "It reads the live issues and answers: what is first, who has it, and what they should do. This takes a few seconds." |
| When the answer appears, point at an issue code. | "The same issue codes as on the screens. It advises. People act." |

## 7. Data connectors and Agent activity

| Do | Say |
|---|---|
| **Setup and information** > **Data connectors**. Point at **How connecting works**. | "Connecting your data: choose the system, test it, match your columns to ours, set how often to pull." |
| Scroll to **Connect a system**. Point at the labels on the cards. | "Cards marked available now work today. Others are added per project. Everything is read only, and passwords are stored encrypted." |
| Click **Agent activity**. | "And this is the record of what the agent did: what it detected, whom it handed it to, what it escalated and what it verified. Nothing is a black box." |

## 8. Closing

| Do | Say |
|---|---|
| Go back to **Issues**. | "So when something goes wrong, your team sees what, where, who, how long and what to do, and proof that it was fixed. The next step is your sensor data and your shift roster, so we can try it on a normal week at your plant." |

## If they ask

| Question | Say |
|---|---|
| Is this real data? | "No. It is simulated and generated data for the proof of concept, and the app labels it." |
| Can it control equipment? | "No, by design." |
| Is the AI deciding what is a fault? | "No. Rules and limits decide. The AI chat explains and answers." |
| Are you tracking where our people are? | "No. The figure only shows the stage of the response." |
| Is it ready for production? | "Not yet. Sign-in has no password or roles, and live sensor feeds still need to be connected." |
