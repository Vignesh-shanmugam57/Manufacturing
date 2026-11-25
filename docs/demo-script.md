# Utilities Management Agent: end-to-end talk script

**Do** is what you click. **Say** is what you speak. `[name]` is whoever the screen shows: it changes with the shift.

| Part | Topic | Minutes |
|---|---|---|
| 1 | Opening and sign in | 1 |
| 2 | How it works (architecture) | 3 |
| 3 | Issues | 3 |
| 4 | Plant map and live response | 4 |
| 5 | The closed record | 1 |
| 6 | Plant overview | 2 |
| 7 | Ask the agent | 2 |
| 8 | Data connectors | 2 |
| 9 | Agent activity | 1 |
| 10 | Closing and questions | 1 |

Short on time? Do parts 1, 3, 4 and 10 (about 9 minutes).

---

## Before the client arrives

| # | Do |
|---|---|
| 1 | Start the app, open it in a **wide or full-screen** window and sign in. |
| 2 | **Setup and information** > **Data connectors** > open **Mock data for the proof of concept** > **Re-create mock data (about 20 s)**. This brings back the open gas issue. |
| 3 | Open **Issues**. Check for 6 open issues, 1 of them critical. |
| 4 | Open **Ask the agent** once and ask any question, so the first answer in front of the client is not the slow one. Then go back to **Issues**. |
| 5 | Sign out if you want to show the sign-in screen. |

The **Reset demo** button on the plant map does **not** reopen a closed issue. Use step 2.

---

## 1. Opening and sign in

| Do | Say |
|---|---|
| Show the sign-in screen. | "Good morning. Every plant knows this moment: something goes wrong on the utilities side and the questions start. What is wrong? Where is it? Who has to go? How long has it been? And was it really fixed?" |
| | "Today the answers sit in different places: a control screen, phone calls, someone's notebook. This agent puts them in one place, for your plant team." |
| | "What you will see is a proof of concept. The plant readings, the team and the history are simulated." |
| Type your work email and name, pick a role, click **Continue**. | "I sign in, and the first thing the team sees is not a dashboard. It is the list of problems." |
| Point at the left menu. | "Three pages for the plant team: Issues, Plant map and Plant overview. Setup and information sits below. And you can ask the agent a question at any time." |

## 2. How it works (architecture)

| Do | Say |
|---|---|
| **Setup and information** > **How it works**. Let it play. | "Before the demo, here is how it is put together. This flow plays by itself." |
| Click step **1 Sources**. | "It starts with data. Today a built-in simulator produces readings for seven utilities: compressed air, steam, chilled water, cooling tower, HVAC, water and gas. Your databases, web services and files connect here too, read only. Live SCADA and PLC feeds are not connected yet." |
| Click **2 Database**. | "The database holds the stored history, every issue with its timeline, and the team roster." |
| Click **3 Backend**. | "The monitoring engine checks the equipment every second. It keeps one set of facts, so every screen shows the same thing." |
| Click **4 AI chat**. | "The AI chat answers questions in plain language from those same facts. It can read and advise. It cannot change an issue or operate equipment." |
| Click **5 Detect**. | "Detection uses engineering limits and known fault patterns. These are fixed rules, so the same reading always gives the same result. It is not a language model guessing." |
| Click **6 Alert**. | "A problem is raised once, with the reading, what was expected, the probable cause and what to do." |
| Click **7 Assign**. | "The agent picks the person: right team, on shift now, covering that zone. If a critical issue is not picked up in two minutes, it escalates." |
| Click **8 Resolve**. | "Then a person acts. They acknowledge, go to the equipment, fix it and record what they did." |
| Click **9 Verify**. | "And the issue closes only when fresh readings are back to normal." |
| Click **10 Monitor**. | "Then it keeps watching, and the loop starts again. Now let me show you one real round of this loop." |

## 3. Issues

| Do | Say |
|---|---|
| Click **Issues**. | "This is where a shift starts." |
| Point at the number tiles. | "How many issues are open, how many need attention, how many nobody has picked up, how many are overdue, and how quickly the team responds and closes." |
| Point at the order of the list. | "Nobody has to sort anything. What needs attention first is at the top." |
| Click **Major**, then **All severities**. | "I can filter by severity, or by zone if I only look after one area." |
| Point at one orange or yellow row. | "Each row answers the questions: what is wrong, where, who, how long, and what to do." |
| If a row says the shift has ended, open it and point at the notice. | "If the person's shift has ended, it says so and suggests who is on now, so nothing is lost at handover." |
| Click the **red critical row** (combustible gas). | "Here is the critical one: a gas reading above its limit." |
| Point at **What happened**. | "What is wrong: the actual reading next to the expected range, and what it supplies." |
| Point at **What to do**. | "What to do, in plain words." |
| Point at **Where and who**. | "Where: the Gas Station, at the regulating skid. Who: [name], safety officer, with an extension and shift." |
| Point at the **timer**. | "How long: a live timer, against a two minute target to acknowledge." |
| Scroll to **Timeline**. | "And every step so far, with its time. Detected, cause worked out, people notified, escalated." |

## 4. Plant map and live response

| Do | Say |
|---|---|
| Click **Show on plant map**. | "Now the same issue on the plant itself. The equipment is pulsing red." |
| Point at the **Systems** panel. | "Each system shows its state, with a count when something is open." |
| Point at the right-hand panel: **Readings**, then click **Trends**, then **Readings** again. | "For any machine I see its live readings, the normal range, its trend and its alarms." |
| Point at the **Live response** strip. | "These five steps are the life of this issue: detect, notify, go, fix, verify." |
| Point at the name tag by the **Control room**. | "The agent has notified [name]. It is waiting for them to take it." |
| Click **Acknowledge** in the strip. | "I acknowledge. The issue now has an owner who has accepted it." |
| Watch the figure walk (about 8 seconds). | "You can follow [name] heading to the equipment. This shows the stage of the response. It is a visualisation, not location tracking." |
| When they arrive, point at the **blue ring**. | "On site and working. The gas reading on the right is still high, because nothing is fixed yet." |
| Type `Regulator replaced and joints leak tested`. Click **Record the fix** and wait for the button to finish. | "I record what was done. Next time this happens, the team can see what worked." |
| Point at the **green scan** and the falling reading. Wait about 15 seconds. | "This is the important part. Nobody can simply press done. The agent checks the fresh readings." |
| Click **Verify with telemetry**. If it refuses, wait a few seconds and click again. | "The readings are inside the limits, so the issue closes. If they were not, it would refuse and say why." |
| Point at the **top bar**, the **menu badge** and **Gas** in Systems. | "Without refreshing: one alert fewer, the badge has dropped, gas is green. One fact, shown the same everywhere." |
| Let the figure walk back. | "Closed, and [name] heads back." |
| Click **Chilled water** in Systems, then **Full factory**. | "I can also look at one system at a time and see only its equipment and pipes." |

## 5. The closed record

| Do | Say |
|---|---|
| Click **Issues**, then **Closed**. | "Nothing disappears. Closed issues are kept." |
| Open the gas issue you just closed. | "Here is the full story: who acknowledged, what was done, and the readings that proved it. This is your shift report and your audit trail." |
| Click **Open**. | "And the open list now has one issue fewer." |

## 6. Plant overview

| Do | Say |
|---|---|
| Click **Plant overview**. | "This is the manager's view: one tile per utility." |
| Point at the **Gas** tile. | "Gas reads all normal, because we just closed it." |
| Click **Chilled water**. | "For a utility with a problem: usage today against yesterday and the normal range, and below it the reading behind the problem against its limit. The usage figures here are modelled demo data." |
| Point at the peak hour and energy cost. | "Peak hour so far, and an estimate of the energy cost where there is an electricity meter." |
| Click **Last 7 days**. | "And the week at a glance." |
| Point at **Needs attention**. | "On the right, what to deal with next, and who has it." |

## 7. Ask the agent

| Do | Say |
|---|---|
| Click **Ask the agent**. | "If you would rather ask than click, just ask." |
| Click **What needs attention first right now...** and wait. | "It reads the live issues, so this takes a few seconds." |
| Point at the issue codes and names in the answer. | "Same issue codes and same people as on the screens. It tells you what is first, who has it and what to do." |
| Type `Who is on shift for the Gas Station, and what is open there?` | "It knows the roster too. And notice the gas issue we closed is no longer open." |
| Type `Open the gas isolation valve now.` | "Now watch this. I ask it to operate equipment." |
| Point at the refusal. | "It refuses and sends me to the certified operator. That is deliberate. The agent advises, people act." |

## 8. Data connectors

| Do | Say |
|---|---|
| **Setup and information** > **Data connectors**. Point at **How connecting works**. | "So far this was demo data. This is where your own data comes in, in four steps." |
| Scroll to **Connect a system**. Point at the card labels. | "Databases, web services, files. Cards marked available now work today. Others are added per project, and the app says so instead of pretending." |
| On **Demo plant gateway**, click **Connect**, then **Next**. | "Let me show the steps with a built-in demo source." |
| Click **Test connection**, wait for the green message, then **Next**. | "First test the connection. Nothing is saved yet." |
| Point at the matched fields, then **Next**. | "It matches your column names to ours automatically. You fix any it cannot match." |
| Point at **How often**, then click **Cancel**. | "Then choose how often to pull. I will stop here so we add no data. Connections are read only and passwords are stored encrypted. Today this feeds history and analysis. Feeding your live sensors into monitoring is the next step." |

## 9. Agent activity

| Do | Say |
|---|---|
| Click **Agent activity**. | "And this is the record of what the agent did." |
| Point at the tiles, ending on **actions on equipment: 0**. | "What it detected and handed over, and this number: zero actions on equipment." |
| Click an item in the list. | "Behind every issue are the steps it took, with the evidence. Nothing is a black box." |
| Click **History analysis**. | "It can also analyse your stored history for abnormal usage, downtime links and efficiency ideas. This only reads." |

## 10. Closing

| Do | Say |
|---|---|
| Go back to **Issues**. | "To sum up. When something goes wrong, your team sees what, where, who, how long and what to do, and proof that it was fixed." |
| | "The next step is your sensor data and your shift roster, so we can try it through a normal week at your plant. What would you like to see again?" |

---

## If they ask

| Question | Say |
|---|---|
| Is this real data? | "No. It is simulated and generated data for the proof of concept." |
| Can it control equipment? | "No, by design." |
| Is the AI deciding what is a fault? | "No. Rules and limits decide. The AI chat explains and answers." |
| Are you tracking where our people are? | "No. The figure only shows the stage of the response." |
| Can it connect to our SCADA or PLCs? | "Not yet in this build. It is added per project." |
| Does it send SMS or email? | "Notifications are recorded in the app. Sending them outside is not set up in this proof of concept." |
| Is it ready for production? | "Not yet. Sign-in has no password or user permissions, and live sensor feeds still need to be connected." |

## If something goes wrong

| What you see | Do |
|---|---|
| Pages are slow or say "Reading…" | Wait a moment. Just after a start the app takes a minute or two. |
| No gas issue to show | Re-create the mock data (see "Before the client arrives", step 2). |
| **Verify** is refused | Wait a few seconds and click it again. |
| The plant map looks crowded in a small window | Make the window wider, or close the **Tickets** panel. |
| A button stays grey | The save is still running. Wait for it. |
